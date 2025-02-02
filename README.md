
---

## **📌 YouTube Sentiment Analysis**
🚀 **A Python project that analyzes YouTube video sentiment based on comments and video transcripts.**  
This program determines whether comments **agree or disagree** with the sentiment expressed in the video.

---

## **📖 Table of Contents**
- [🌟 Features](#-features)
- [🛠 Installation](#-installation)
- [⚙️ How to Use](#-how-to-use)
- [🔄 Modifications & Customization](#-modifications--customization)
- [💡 Using a Different Dataset](#-using-a-different-dataset)
- [🚀 Example Output](#-example-output)
- [🔧 Troubleshooting](#-troubleshooting)
- [📜 License](#-license)

---

## **🌟 Features**
✅ Fetches **YouTube video comments** using the **YouTube Data API v3**  
✅ Retrieves **video transcripts** (if available) to determine the video’s sentiment  
✅ Uses a **Naïve Bayes Classifier** trained on **Sentiment140 (Twitter-based dataset)**  
✅ Determines whether **comments agree or disagree** with the video  
✅ Supports fetching **top comments or latest comments**  
✅ Handles **up to 5000 comments per video** with pagination  
✅ Fully customizable to work with **other sentiment datasets**  

---

## **🛠 Installation**
### **1️⃣ Clone the Repository**
```bash
git clone https://github.com/your-username/youtube-sentiment-analysis.git
cd youtube-sentiment-analysis
```

### **2️⃣ Install Required Dependencies**
```bash
pip install -r requirements.txt
```

### **3️⃣ Install Sentiment140 Dataset (Required)**
**This repository does not include the Sentiment140 dataset.**  
You must **download it manually** or use another dataset (see [Using a Different Dataset](#-using-a-different-dataset)).  

#### **📥 Download Sentiment140**
1. Go to **[Sentiment140 Dataset](http://help.sentiment140.com/for-students)**
2. Download `training.1600000.processed.noemoticon.csv`
3. Rename it to **`sentiment140.csv`**
4. Move it to your project directory:
   ```
   youtube-sentiment-analysis/
   ├── youtube_comments.py
   ├── sentiment_analysis.py
   ├── sentiment140.csv  <-- ✅ Place it here!
   ├── requirements.txt
   ├── README.md
   ```

---

## **⚙️ How to Use**
### **1️⃣ Run `youtube_comments.py` to Fetch Comments & Analyze Video Sentiment**
```bash
python youtube_comments.py
```
- **Enter a YouTube Video URL**  
- **Choose how many comments to fetch**  
- **Select "top" or "latest" comments**  
- The script will:
  - Fetch comments
  - Get the video transcript (if available)
  - Analyze the **video’s sentiment**
  - Save everything to `youtube_comments.csv`

### **2️⃣ Run `sentiment_analysis.py` to Analyze Comments**
```bash
python sentiment_analysis.py
```
- This script will:
  - Read comments from `youtube_comments.csv`
  - Predict **whether comments agree or disagree** with the video
  - Display the **final analysis results**

---

## **🔄 Modifications & Customization**
### **Change the Number of Comments Fetched**
Modify this line in `youtube_comments.py`:
```python
max_comments = 500  # Change this to any number (max 5000 recommended)
```

### **Use "Top" or "Latest" Comments by Default**
Change this line in `youtube_comments.py`:
```python
sort_by = "relevance"  # Change to "time" for latest comments
```

### **Modify Sentiment Model Parameters**
Edit `train_sentiment_model()` in `sentiment_analysis.py`:
```python
vectorizer = CountVectorizer(max_features=5000)  # Increase feature size for better accuracy
```

---

## **💡 Using a Different Dataset**
This project **uses Sentiment140**, but you can replace it with another sentiment dataset.

### **1️⃣ Download a New Dataset**
Find another **labeled** dataset where text is classified as **positive/negative** (e.g., IMDB, Amazon reviews, Reddit comments).

### **2️⃣ Modify `load_sentiment140()` in `sentiment_analysis.py`**
Replace:
```python
df = pd.read_csv("sentiment140.csv", encoding="latin1", usecols=[0, 5], names=["sentiment", "text"])
df["sentiment"] = df["sentiment"].replace({0: "neg", 4: "pos"})
```
With:
```python
df = pd.read_csv("your_new_dataset.csv")
df["sentiment"] = df["sentiment_column"].map({1: "pos", 0: "neg"})  # Modify mapping based on your dataset
```

---

## **🚀 Example Output**
```
🔗 Paste YouTube video URL: https://www.youtube.com/watch?v=dQw4w9WgXcQ
🔢 Enter the number of comments to fetch (max 5000 recommended): 500
📌 Fetch top comments or latest comments? (Enter 'top' or 'latest'): top
✅ YouTube comments and video sentiment saved to `youtube_comments.csv`
🎥 Video Sentiment: negative
💬 Total Comments Fetched: 500

📊 **Sentiment Analysis Results:**
Total Comments Analyzed: 500
👍 Agreeing Comments: 350 (70.00%)
👎 Disagreeing Comments: 150 (30.00%)
```

---

## **🔧 Troubleshooting**
### **1️⃣ `sentiment140.csv not found`**
**Solution:** Download it manually from [Sentiment140](http://help.sentiment140.com/for-students) and move it into your project directory.

### **2️⃣ `googleapiclient.errors.HttpError: quotaExceeded`**
**Cause:** You’ve reached your **YouTube API quota limit**.  
**Solution:** Wait 24 hours or apply for a **higher quota limit** in your [Google Cloud Console](https://console.cloud.google.com/).

### **3️⃣ `ModuleNotFoundError: No module named 'googleapiclient'`**
**Solution:** Install missing dependencies:
```bash
pip install -r requirements.txt
```

### **4️⃣ `youtube_comments.csv not found`**
**Cause:** You ran `sentiment_analysis.py` before `youtube_comments.py`.  
**Solution:** Run:
```bash
python youtube_comments.py
```
**first**, then run:
```bash
python sentiment_analysis.py
```

---
