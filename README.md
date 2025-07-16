# Profiling Telegram Stories Viewers

A script for profiling the viewers of your Telegram stories. It walks through all your published and highlighted (but not archived, unfortunately) stories, and records the viewers into .csv files.

## Usage

```bash
pip3 install matplotlib telethon python-dotenv
python3 main.py
```

## Visualization

Using the .csv files, you can visualize the views of a certain viewer of your stories.

```bash
python visualize.py <folder> <viewer_user_id>
```