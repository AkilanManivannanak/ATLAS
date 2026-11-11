# Payments glossary

Plain-English definitions of the terms used across ATLAS-Σ. Each entry: one or two sentences, then where ATLAS models it.

## Rails and settlement

### RTGS (real-time gross settlement)
Each payment settles on its own, in full, the moment it’s processed. Nothing is batched or netted.
That makes it safe but cash-hungry: the sender needs the whole amount available.
Fedwire Funds is the US example.
In ATLAS: the rtgs rail, and the priority-queue and FIFO policies in src/atlas/settlement/.

### LSM (liquidity-saving mechanism)
A queue attached to RTGS that holds payments and periodically releases sets of them that offset each other, so less cash is needed.
In ATLAS: the lsm rail, which runs cycles during the day and a final funding cycle before close.

### Netting and gridlock
Gridlock: A is waiting on B’s payment, B on C’s, and C on A’s, so nobody can pay first.
Netting settles the whole loop at once, and each bank only needs cash for its net position.
In ATLAS: bilateral and multilateral netting, plus an exact solver, in settlement/netting.py. Finding: at realistic cash levels there’s little gridlock, so netting barely matters (docs/19).

### FedNow
The Federal Reserve’s instant payment service. It runs 24/7, payments are final in seconds, and each payment has a cap (participants set their own lower limits).
In ATLAS: the fednow rail, which rejects a payment if the sender lacks funds. There is also the new shared-master-account option.

### RTP
The Clearing House’s private instant payment network, also with a $10M cap per payment.
Banks prefund a joint account, and payments draw on that prefunded balance.
In ATLAS: the rtp rail, kept as its own pool because that matches how RTP really works.

## Liquidity and credit

### Fed master account
The one account a bank holds at the Federal Reserve. Fedwire and FedNow both settle in it.
In ATLAS: the fednow_shared_master option, where FedNow and RTGS share one balance.

### Intraday credit (daylight overdraft)
The Fed lets a bank’s account go negative during the day, within limits, so payments don’t stall.
The bank must be back to zero or positive by the end of the day.
In ATLAS: credit_limit_minor on accounts, and peak credit use is reported for each run.

### PSR daylight-overdraft fee
The Fed’s charge for the uncollateralized part of that overdraft. It’s measured minute by minute and works out to 50 basis points a year on the average overdraft.
In ATLAS: _psr_fee in sim/day.py, with a test against the Fed’s worked example.

### Collateralized vs uncollateralized credit
If a bank pledges securities, its overdraft is collateralized and carries no PSR fee.
The unbacked part is what gets charged.
In ATLAS: the collateralized_credit_bp setting, which defaults to 60% collateralized.
## Messages and records

### ISO 20022 pacs.008 / pacs.009
The global XML message standard banks use to send payments.
pacs.008 is a customer payment; pacs.009 is a bank-to-bank transfer.
In ATLAS: src/atlas/iso20022/, which can write and read these messages.

### camt.053 statement
The ISO 20022 end-of-day account statement: opening balance, every entry, and closing balance.
In ATLAS: every account’s statement is generated and checked against the ledger, and they must match exactly.

### Event-sourced, hash-chained ledger
Instead of overwriting balances, every change is stored as an event.
Each event includes a fingerprint (hash) of the one before it, so any tampering breaks the chain.
Replaying all events must rebuild exactly the same balances.
In ATLAS: src/atlas/ledger/, and every result in the repo is admitted only after a successful replay.
