Run the weekly stock picker analysis.

Usage: /run-stock-picker [industry] [months]

Examples:
  /run-stock-picker technology 6
  /run-stock-picker finance 3
  /run-stock-picker healthcare 6

Steps:
1. Parse $ARGUMENTS — first token is the industry (default: "technology"), second is lookback months (default: 6).
2. The project directory is the root of this repo. Run all commands from there using `uv run python` so the virtualenv is used automatically.
3. Run the analysis with a Python one-liner:
   ```
   uv run python -c "
   import logging
   logging.basicConfig(level=logging.INFO, format='[%(name)s] %(levelname)s: %(message)s')
   from stock_picker_agents import create_custom_config, create_orchestrator
   config = create_custom_config(max_tickers=20, forecast_days=7)
   orchestrator = create_orchestrator(config)
   results = orchestrator.run_analysis('<INDUSTRY>', lookback_months=<MONTHS>)
   if results['success']:
       print(f'Done: {results[\"successful_forecasts\"]}/{results[\"total_tickers\"]} tickers. Report: {results[\"report_path\"]}')
   else:
       print(f'Failed: {results.get(\"error\")}')
   "
   ```
   Substitute the parsed industry and months into the command.
4. Report the output file path and a brief summary of successful/failed tickers to the user.
