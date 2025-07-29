from transformers import AutoTokenizer, AutoModelForTokenClassification, Trainer, TrainingArguments, DataCollatorForTokenClassification
from datasets import load_dataset, Dataset
import json
import os

# JSON dosyasını oku
data = []
with open("feedback_dataset.json", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            data.append(json.loads(line))
        except json.JSONDecodeError:
            print("⚠️ Hatalı satır atlandı:", line)


# HuggingFace formatına uygun hale getir
examples = {
    "tokens": [],
    "labels": []
}

# Dummy NER formatı oluştur
for item in data:
    tokens = []
    labels = []
    for text, label in zip(item["inputs"], item["labels"]):
        # Basitçe sadece label'ı tüm kelimelere uygula (örnek format için)
        tokenized = text.split()
        tokens.extend(tokenized)
        labels.extend(["B-ENT"] + ["I-ENT"] * (len(tokenized) - 1))
    examples["tokens"].append(tokens)
    examples["labels"].append(labels)

dataset = Dataset.from_dict(examples)

# Etiketleri sayısallaştır
unique_labels = list(set(l for label_list in examples["labels"] for l in label_list))
label2id = {l: i for i, l in enumerate(sorted(unique_labels))}
id2label = {i: l for l, i in label2id.items()}

# Tokenizer ve model
model_name = "distilbert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(
    model_name,
    num_labels=len(label2id),
    id2label=id2label,
    label2id=label2id
)

# Tokenize edilmiş veri
def tokenize_and_align_labels(example):
    tokenized = tokenizer(example["tokens"], is_split_into_words=True, truncation=True, padding="max_length", max_length=128)
    word_ids = tokenized.word_ids()
    labels = []
    for word_idx in word_ids:
        if word_idx is None:
            labels.append(-100)
        else:
            labels.append(label2id[example["labels"][word_idx]])
    tokenized["labels"] = labels
    return tokenized

tokenized_dataset = dataset.map(tokenize_and_align_labels)

# Eğitim ayarları
args = TrainingArguments(
    output_dir="output_model",
    evaluation_strategy="no",
    learning_rate=2e-5,
    per_device_train_batch_size=4,
    num_train_epochs=3,
    weight_decay=0.01,
    logging_dir="./logs",
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=tokenized_dataset,
    tokenizer=tokenizer,
    data_collator=DataCollatorForTokenClassification(tokenizer)
)

# Eğitimi başlat
trainer.train()

# Modeli kaydet
output_dir = "output_model"
trainer.save_model(output_dir)
tokenizer.save_pretrained(output_dir)

print(f"✅ Model ve tokenizer '{output_dir}/' klasörüne kaydedildi.")