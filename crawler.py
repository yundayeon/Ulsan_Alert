import json
import os
import requests
import time
import traceback
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

NOTICE_URL = "https://sw.ulsan.ac.kr/site/swulsan/notices?page_size=20&page=1"
STATE_FILE = "state.json"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


def load_seen_ids():
    if not os.path.exists(STATE_FILE):
        return set()

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return set(data.get("seen_ids", []))


def save_seen_ids(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"seen_ids": list(ids)},
            f,
            ensure_ascii=False,
            indent=2
        )


def send_discord(post):
    message = (
        "📢 **울산대 SW중심대학사업단 새 공지**\n\n"
        f"**{post['title']}**\n"
        f"작성일: {post['date']}\n"
        f"ID: {post['id']}\n"
        f"{post['url']}"
    )

    response = requests.post(
        WEBHOOK_URL,
        json={"content": message},
        timeout=10
    )

    response.raise_for_status()


def crawl_notices(seen_ids, first_run=False):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            page = browser.new_page(locale="ko-KR")
            page.goto(
                NOTICE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            row_selector = '[role="row"][data-rowindex]'
            page.locator(row_selector).first.wait_for(
                state="visible",
                timeout=30000,
            )

            # 상세 페이지에 들어가기 전에 목록 정보부터 수집
            posts = []

            for row in page.locator(row_selector).all():
                post_id = row.get_attribute("data-id")

                if not post_id:
                    continue

                posts.append({
                    "id": int(post_id),
                    "title": row.locator(
                        '[data-field="title"]'
                    ).inner_text().strip(),
                    "date": row.locator(
                        '[data-field="insert_date"]'
                    ).inner_text().strip(),
                })

            # 첫 실행에는 ID 저장만 하므로 상세 URL 확인 생략
            if first_run:
                return posts

            new_posts = [
                post for post in posts
                if post["id"] not in seen_ids
            ]

            print(f"목록 {len(posts)}개 / 새 글 {len(new_posts)}개")

            list_url = page.url

            # 새 글만 클릭해서 상세 URL 확인
            for index, post in enumerate(new_posts):
                if index > 0:
                    page.goto(
                        list_url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                title_cell = page.locator(
                    f'{row_selector}[data-id="{post["id"]}"] '
                    '[data-field="title"]'
                )

                title_cell.click(timeout=30000)

                # URL이 실제로 바뀔 때까지 대기
                page.wait_for_url(
                    lambda url: url != list_url,
                    timeout=30000,
                )

                post["url"] = page.url

            return new_posts

        finally:
            browser.close()


def main():
    # 크롤링 전에 저장된 ID부터 읽기
    first_run = not os.path.exists(STATE_FILE)
    seen_ids = load_seen_ids()

    posts = crawl_notices(seen_ids, first_run=first_run)

    if not posts:
        print("새로운 게시글이 없거나 목록이 비어 있습니다.")
        return

    if first_run:
        save_seen_ids({post["id"] for post in posts})
        print("첫 실행: 현재 게시글을 저장했습니다. 알림은 보내지 않습니다.")
        return

    for post in posts:
        send_discord(post)

        # 전송 성공한 글은 즉시 저장
        # 다음 글 전송이 실패해도 이미 보낸 글의 중복 알림 방지
        seen_ids.add(post["id"])
        save_seen_ids(seen_ids)

        print(f"Discord 알림 전송 완료: {post['title']}")
        
if __name__ == "__main__":
    main()