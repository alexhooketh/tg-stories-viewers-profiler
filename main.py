import asyncio
import csv
import datetime
import os
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient, functions
from i18n import t

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION")


async def fetch_highlight_viewers():
    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        me = await client.get_me()

        # Create an output directory named with the current timestamp (UTC to avoid TZ ambiguity)
        timestamp_folder = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
        output_dir = Path(os.path.join("results", timestamp_folder))
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1) Fetch all your pinned (highlight) stories
        pinned = await client(
            functions.stories.GetPinnedStoriesRequest(
                peer=me,  # your own profile
                offset_id=0,  # start from the first story
                limit=100,  # max per call
            )
        )
        story_ids = [s.id for s in pinned.stories]
        print(t("Found {count} highlighted stories.", count=len(story_ids)))

        # 2) For each pinned story, page through its full viewer list
        story_viewers = {}
        for sid in story_ids:
            viewers = []
            offset = ""  # pagination token
            while True:
                vr = await client(
                    functions.stories.GetStoryViewsListRequest(
                        peer=me, id=sid, offset=offset, limit=100
                    )
                )
                for i in range(len(vr.views)):
                    assert vr.users[i].id == vr.views[i].user_id
                    viewers.append(
                        (
                            vr.users[i].id,
                            (vr.users[i].first_name or "")
                            + " "
                            + (vr.users[i].last_name or ""),
                            (vr.users[i].username or ""),
                            vr.views[i].date,
                        )
                    )
                if not vr.next_offset:
                    break
                offset = vr.next_offset

            story_viewers[sid] = viewers
            print(t("Story {id}: {viewer_count} viewers", id=sid, viewer_count=len(viewers)))

            # Sort viewers chronologically (oldest first) by the view date
            viewers.sort(key=lambda v: v[3])

            # Write viewers to CSV inside the timestamped folder
            csv_path = output_dir / f"{sid}.csv"
            with csv_path.open("w", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["user_id", "full_name", "username", "date"])
                for record in viewers:
                    writer.writerow(record)

        return story_viewers


if __name__ == "__main__":
    all_viewers = asyncio.run(fetch_highlight_viewers())
