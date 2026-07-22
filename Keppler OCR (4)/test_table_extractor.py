import pandas as pd

table_data = [['Name', 'Age'], ['John', '30']]
max_cols = max(len(row) for row in table_data)
for row in table_data:
    while len(row) < max_cols:
        row.append("")

if len(table_data) > 1:
    df = pd.DataFrame(table_data[1:], columns=table_data[0])
else:
    df = pd.DataFrame(table_data)

print(df)

table_data = [['Single Value']]
if len(table_data) > 1:
    df = pd.DataFrame(table_data[1:], columns=table_data[0])
else:
    df = pd.DataFrame(table_data)

print(df)
