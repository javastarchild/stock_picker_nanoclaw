Show the most recent stock picker forecast report.

Steps:
1. List files in the `report/` subdirectory of this project (relative to the repo root), sorted by modification time (newest first).
2. Find the newest *_summary.txt file and the newest *.csv file (non-checkpoint).
3. Display the full contents of the summary .txt file.
4. Display the first 20 rows of the CSV file in a readable table format using pandas:
   ```
   python -c "
   import pandas as pd, glob, os
   files = sorted(glob.glob('report/*.csv'), key=os.path.getmtime, reverse=True)
   if files:
       df = pd.read_csv(files[0])
       print(df.to_string(index=False))
   else:
       print('No reports found.')
   "
   ```
5. Tell the user the full path of the report file shown.
