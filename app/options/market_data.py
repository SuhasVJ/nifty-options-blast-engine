class OptionMarketData:

    def __init__(self):
        self.data = {}

    def update(self, tick):

        token = tick["instrument_token"]

        is_first_tick = token not in self.data

        self.data[token] = {
            "instrument_token": token,
            "last_price": tick.get("last_price"),
            "volume": tick.get("volume_traded"),
            "oi": tick.get("oi"),
            "buy_quantity": tick.get("buy_quantity"),
            "sell_quantity": tick.get("sell_quantity"),
            "timestamp": tick.get("exchange_timestamp")
        }

        return is_first_tick