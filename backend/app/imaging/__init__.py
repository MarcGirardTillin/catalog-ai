"""Image Processing Service — business verbs over provider adapters.

The stable internal API is the Python signatures in :mod:`app.imaging.service`;
providers (Photoroom, FASHN, local) stay hidden behind them (anti-corruption
layer). Staging is ephemeral local disk (:mod:`app.imaging.staging`); the
durable store is Xano.
"""
