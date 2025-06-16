import pandas as pd
import os

folder_path = 'logs/'
file_list = sorted([f for f in os.listdir(folder_path) if f.endswith('.xlsx')])
main_file = os.path.join(folder_path, file_list[-1])
main_df = pd.read_excel(main_file)
combined_df = pd.DataFrame()

combined_df = pd.concat([combined_df, main_df], ignore_index=True)
for i, file in enumerate(file_list[-2::-1]):
    file_path = os.path.join(folder_path, file)
    df = pd.read_excel(file_path, skiprows=1, header=None)
    combined_df = pd.concat([combined_df, df], ignore_index=True)

output_path = os.path.join(folder_path, 'combined_output.xlsx')
combined_df.to_excel(output_path, index=False)
