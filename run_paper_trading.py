        filename = self.reporter.generate()
        print(f"✅ Report saved: {filename}", flush=True)


if __name__ == "__main__":
    trader = PaperTrader()
    try:
        asyncio.run(trader.run())
    except KeyboardInterrupt:
        print("\n\nStopping...", flush=True)
        trader.print_performance()
        trader.generate_excel_report()