import pandas as pd
import pyodbc


conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=DESKTOP-6OQRVBE\\SQLEXPRESS;'
    'DATABASE=OCRPROJECT;'
    'Trusted_Connection=yes;'
)
# FeedbackLogs tablosunu çek
df = pd.read_sql("SELECT DocumentID, FieldName, PredictedValue, CorrectedValue FROM FeedbackLogs", conn)
conn.close()

# Dataset hazırlama
dataset = []

for doc_id, group in df.groupby("DocumentID"):
    entry = {
        "inputs": [f"{row.FieldName}: {row.PredictedValue}" for _, row in group.iterrows()],
        "labels": [row.CorrectedValue for _, row in group.iterrows()]
    }
    dataset.append(entry)

# CSV ve JSON olarak kaydet
df.to_csv("feedback_raw.csv", index=False)
pd.DataFrame(dataset).to_json("feedback_dataset.json", orient="records", lines=True)

print("✅ Eğitim verisi başarıyla oluşturuldu: feedback_raw.csv ve feedback_dataset.json")
