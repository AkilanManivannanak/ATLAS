# Forecasting methodology

* **Target:** large-value net outflow (sent − received instruction value) per institution per 15-minute bucket. It is exogenous to the settlement policy in the simulator, so there is no policy leakage.
* **Panel:** fixed topology (`topology_seed`) with day-specific arrival seeds, so "the same bank on another day" is well defined.
* **Splits:** whole days → train (12) / validation (4) / test (4). An out-of-distribution test uses days generated with 50% more payments and fatter amount tails.
* **Models:** historical mean (same bank and bucket), seasonal naive (last training day), ridge regression (time-of-day harmonics, tier, intraday lags, cumulative flow, system activity, horizon), histogram gradient boosting (scikit-learn; the LightGBM-style baseline).
* **Uncertainty:** split conformal prediction on validation days, using signed residual quantiles for the quantile forecasts and the absolute-residual quantile for a 90% interval.
* **Metrics:** MAE, RMSE, MASE (scaled by the in-sample day-to-day seasonal-naive MAE), mean pinball loss, CRPS ≈ 2 × mean pinball over the quantile grid, empirical interval coverage, mean width, calibration error.
* **Not implemented:** LSTM, Temporal Fusion Transformer, graph-conditioned models. They are the next forecasting increment and must beat the ridge baseline here to be adopted.
* **Known property of the generator:** arrivals have no intraday autocorrelation, so the horizon has little effect. This limits what sequence models can show and is listed in `20_known_limitations.md`.
