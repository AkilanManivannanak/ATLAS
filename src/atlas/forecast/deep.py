"""Sequence forecasters in PyTorch (``atlas-forecast-deep-v1``): a GRU and a small Transformer encoder.

Optional: needs ``torch`` (``pip install -e ".[deep]"``). Both models read the last ``window`` 15-minute buckets
of a bank's own flow, the system-wide flow and time-of-day encodings, plus the bank's tier and the horizon, and
predict the bank's flow ``h`` buckets ahead. They implement the same ``fit`` / ``predict`` interface as the
classical models, so they are scored by the same ``evaluate`` function, on the same whole-day splits, with the
same conformal intervals.

Training: Adam, Huber loss, early stopping on held-out *training days* (never validation or test days), fixed
seeds, CPU. The study in ``scripts/deep_forecast_study.py`` reports them next to ridge and gradient boosting at
two training-set sizes, because a sequence model with a few thousand samples is not a fair test.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from .models import _Base

DEEP_VERSION = "atlas-forecast-deep-v1"


def _torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - exercised only without torch
        raise ImportError("the deep forecasters need PyTorch: pip install torch") from exc
    return torch


def pick_device(prefer: str = "auto") -> str:
    """``auto`` uses a CUDA GPU or Apple-silicon GPU when PyTorch can see one, otherwise the CPU."""
    torch = _torch()
    if prefer != "auto":
        return prefer
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _windows(panel: dict, day_idx: Sequence[int], h: int, scale: dict[int, float], window: int):
    days = panel["days"]
    n_b = days.shape[2]
    seqs, statics, ys, keys = [], [], [], []
    for d in day_idx:
        sys_flow = days[d].sum(axis=0)
        for i, inst in enumerate(panel["institutions"]):
            core = 1.0 if panel["tiers"][inst] == "core" else 0.0
            own = days[d, i] / scale[i]
            sysn = sys_flow / (scale[i] * days.shape[1])
            for origin in range(0, n_b - h):
                seq = np.zeros((window, 4), dtype=np.float32)
                lo = max(0, origin - window + 1)
                k = origin - lo + 1
                idx = np.arange(lo, origin + 1)
                seq[window - k:, 0] = own[lo:origin + 1]
                seq[window - k:, 1] = sysn[lo:origin + 1]
                seq[window - k:, 2] = np.sin(2 * math.pi * idx / n_b)
                seq[window - k:, 3] = np.cos(2 * math.pi * idx / n_b)
                tod = 2 * math.pi * (origin + h) / n_b
                seqs.append(seq)
                statics.append((core, h / 16.0, math.sin(tod), math.cos(tod), own[:origin + 1].sum() / 10.0))
                ys.append(days[d, i, origin + h] / scale[i])
                keys.append((d, i, origin + h))
    return np.stack(seqs), np.array(statics, dtype=np.float32), np.array(ys, dtype=np.float32), keys


class _TorchForecaster(_Base):
    name = "deep"
    kind = "gru"

    def __init__(self, seed: int = 0, window: int = 16, hidden: int = 32, epochs: int = 60, patience: int = 8, lr: float = 3e-3,
                 batch: int = 256, device: str = "cpu") -> None:
        self.device = device           # "cpu" (default, reproducible), "cuda", "mps" or "auto"
        self.seed, self.window, self.hidden, self.epochs, self.patience, self.lr, self.batch = seed, window, hidden, epochs, patience, lr, batch
        self.history: list[dict] = []

    def _net(self):
        torch = _torch()
        nn = torch.nn
        hidden, kind = self.hidden, self.kind

        class Net(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                if kind == "gru":
                    self.enc = nn.GRU(4, hidden, batch_first=True)
                else:
                    self.inp = nn.Linear(4, hidden)
                    self.pos = nn.Parameter(torch.zeros(1, 64, hidden))
                    layer = nn.TransformerEncoderLayer(hidden, nhead=4, dim_feedforward=2 * hidden, dropout=0.1, batch_first=True)
                    self.enc = nn.TransformerEncoder(layer, num_layers=2)
                self.head = nn.Sequential(nn.Linear(hidden + 5, hidden), nn.ReLU(), nn.Linear(hidden, 1))

            def forward(self, seq, static):
                if kind == "gru":
                    _, hn = self.enc(seq)
                    z = hn[-1]
                else:
                    z = self.enc(self.inp(seq) + self.pos[:, :seq.shape[1]])[:, -1]
                return self.head(torch.cat([z, static], dim=1)).squeeze(1)

        return Net()

    def fit(self, panel, train, h):
        torch = _torch()
        torch.manual_seed(self.seed)
        torch.set_num_threads(min(4, torch.get_num_threads()))
        train = list(train)
        self.scale = {i: max(1.0, float(np.abs(panel["days"][train, i]).mean())) for i in range(len(panel["institutions"]))}
        n_hold = max(1, len(train) // 5)
        fit_days, hold_days = train[:-n_hold], train[-n_hold:]
        Xs, Xc, y, _ = _windows(panel, fit_days, h, self.scale, self.window)
        Hs, Hc, hy, _ = _windows(panel, hold_days, h, self.scale, self.window)
        self.device = pick_device(self.device)
        t = lambda a: torch.from_numpy(a).to(self.device)
        Xs, Xc, y, Hs, Hc, hy = t(Xs), t(Xc), t(y), t(Hs), t(Hc), t(hy)
        self.model = self._net().to(self.device)
        opt = torch.optim.Adam(self.model.parameters(), lr=self.lr, weight_decay=1e-4)
        loss_fn = torch.nn.HuberLoss(delta=1.0)
        gen = torch.Generator().manual_seed(self.seed)
        best, best_state, bad = float("inf"), None, 0
        self.history = []
        for epoch in range(self.epochs):
            self.model.train()
            perm = torch.randperm(len(y), generator=gen).to(self.device)
            total = 0.0
            for s in range(0, len(y), self.batch):
                b = perm[s:s + self.batch]
                opt.zero_grad()
                loss = loss_fn(self.model(Xs[b], Xc[b]), y[b])
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                opt.step()
                total += loss.item() * len(b)
            self.model.eval()
            with torch.no_grad():
                hold = float(loss_fn(self.model(Hs, Hc), hy))
            self.history.append({"epoch": epoch + 1, "train_loss": round(total / len(y), 5), "holdout_loss": round(hold, 5)})
            if hold < best - 1e-5:
                best, bad = hold, 0
                best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
            else:
                bad += 1
                if bad >= self.patience:
                    break
        if best_state is not None:
            self.model.load_state_dict(best_state)
        self.n_params = sum(p.numel() for p in self.model.parameters())
        self.train_samples = int(len(y))

    def predict(self, panel, day_idx, h):
        torch = _torch()
        Xs, Xc, _, keys = _windows(panel, day_idx, h, self.scale, self.window)
        self.model.eval()
        with torch.no_grad():
            pred = self.model(torch.from_numpy(Xs).to(self.device), torch.from_numpy(Xc).to(self.device)).cpu().numpy()
        return np.array([pred[k] * self.scale[key[1]] for k, key in enumerate(keys)]), keys

    def save(self, path) -> None:
        torch = _torch()
        torch.save({"version": DEEP_VERSION, "kind": self.kind, "window": self.window, "hidden": self.hidden, "scale": self.scale,
                    "state_dict": self.model.state_dict()}, path)


class GRUForecaster(_TorchForecaster):
    name = "gru"
    kind = "gru"


class TransformerForecaster(_TorchForecaster):
    name = "transformer"
    kind = "transformer"
