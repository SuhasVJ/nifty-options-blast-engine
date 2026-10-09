from app.options.greeks import OptionGreeks


greeks = OptionGreeks(
    risk_free_rate=0.06,
    dividend_yield=0.0
)

spot = 22231.80
strike = 22250.0
option_price = 135.35

time_to_expiry = 5 / 365

iv = greeks.implied_volatility(
    market_price=option_price,
    spot=spot,
    strike=strike,
    time_to_expiry=time_to_expiry,
    option_type="CE"
)

delta = greeks.delta(
    spot,
    strike,
    time_to_expiry,
    iv,
    "CE"
)

gamma = greeks.gamma(
    spot,
    strike,
    time_to_expiry,
    iv
)

vega = greeks.vega(
    spot,
    strike,
    time_to_expiry,
    iv
)

theta = greeks.theta(
    spot,
    strike,
    time_to_expiry,
    iv,
    "CE"
)

print("========================================")
print("           GREEKS TEST")
print("========================================")

print(f"Spot:       {spot}")
print(f"Strike:     {strike}")
print(f"Price:      {option_price}")
print(f"IV:         {iv * 100:.2f}%")
print(f"Delta:      {delta:.4f}")
print(f"Gamma:      {gamma:.6f}")
print(f"Vega:       {vega:.4f}")
print(f"Theta/day:  {theta:.4f}")