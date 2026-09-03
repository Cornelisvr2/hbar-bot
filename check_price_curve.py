from binance_klines_client import BinanceKlinesClient
import datetime

def main():
    client = BinanceKlinesClient()
    nu = datetime.datetime.now(datetime.timezone.utc)
    start = nu - datetime.timedelta(hours=48)

    for asset in ["BTC", "HBAR"]:
        print(f"\n=== {asset}, per uur, laatste 48 uur ===")
        klines = client.get_klines(asset, interval="1h", start_time=start.timestamp(), limit=48)
        vorige_close = None
        for k in klines:
            tijd = datetime.datetime.fromtimestamp(k.open_time, tz=datetime.timezone.utc)
            verandering = ""
            if vorige_close:
                pct = (k.close - vorige_close) / vorige_close * 100
                if abs(pct) >= 1.0:
                    verandering = f"  <<<< {pct:+.2f}% t.o.v. vorig uur"
                else:
                    verandering = f"  {pct:+.2f}%"
            print(f"{tijd.strftime('%Y-%m-%d %H:%M')} UTC | close={k.close:.4f}{verandering}")
            vorige_close = k.close

main()
