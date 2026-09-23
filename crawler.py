import json
import os
import requests
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
    url = post.get("url") or NOTICE_URL

    message = (
        "📢 **울산대 SW중심대학사업단 새 공지**\n\n"
        f"**{post['title']}**\n"
        f"작성일: {post['date']}\n"
        f"ID: {post['id']}\n"
        f"{url}"
    )

    response = requests.post(
        WEBHOOK_URL,
        json={"content": message},
        timeout=10
    )

    response.raise_for_status()


def get_post_url(row, page):
    """
    게시글 행에서 실제 상세 페이지 URL을 가져옵니다.

    우선 <a href="...">를 직접 찾습니다.
    링크가 없는 경우에는 data-url, href 등의 속성을 확인합니다.

    기존처럼 게시글을 클릭하고 wait_for_url()로
    30초 동안 페이지 이동을 기다리지 않습니다.
    """

    # 1. 게시글 제목 영역 안의 a 태그 확인
    title_cell = row.locator('[data-field="title"]')

    links = title_cell.locator("a")

    if links.count() > 0:
        href = links.first.get_attribute("href")

        if href:
            return page.url.split("/site/")[0] + href if href.startswith("/") else href

    # 2. 제목 영역 자체에 href가 있는 경우
    href = title_cell.get_attribute("href")

    if href:
        return page.url.split("/site/")[0] + href if href.startswith("/") else href

    # 3. row 자체에 href가 있는 경우
    href = row.get_attribute("href")

    if href:
        return page.url.split("/site/")[0] + href if href.startswith("/") else href

    # 4. data-url 속성 확인
    for selector in [
        '[data-field="title"]',
        'a',
        '[data-url]',
        '[data-href]',
    ]:
        locator = row.locator(selector)

        if locator.count() > 0:
            element = locator.first

            data_url = element.get_attribute("data-url")
            if data_url:
                return (
                    page.url.split("/site/")[0] + data_url
                    if data_url.startswith("/")
                    else data_url
                )

            data_href = element.get_attribute("data-href")
            if data_href:
                return (
                    page.url.split("/site/")[0] + data_href
                    if data_href.startswith("/")
                    else data_href
                )

    return None


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

            posts = []

            rows = page.locator(row_selector)

            for row in rows.all():
                post_id = row.get_attribute("data-id")

                if not post_id:
                    continue

                title = row.locator(
                    '[data-field="title"]'
                ).inner_text().strip()

                date = row.locator(
                    '[data-field="insert_date"]'
                ).inner_text().strip()

                post = {
                    "id": int(post_id),
                    "title": title,
                    "date": date,
                }

                # 첫 실행이 아니면 URL도 확인
                if not first_run:
                    post["url"] = get_post_url(row, page)

                posts.append(post)

            print(f"목록 {len(posts)}개")

            # 첫 실행
            # 현재 게시글만 저장하고 Discord 알림은 보내지 않음
            if first_run:
                return posts

            new_posts = [
                post
                for post in posts
                if post["id"] not in seen_ids
            ]

            print(f"새 글 {len(new_posts)}개")

            # URL 확인 결과 출력
            for post in new_posts:
                print(
                    f"새 글: {post['title']} "
                    f"(ID: {post['id']}, URL: {post.get('url')})"
                )

            return new_posts

        finally:
            browser.close()


def main():
    # 저장된 게시글 ID 확인
    first_run = not os.path.exists(STATE_FILE)

    seen_ids = load_seen_ids()

    posts = crawl_notices(
        seen_ids,
        first_run=first_run
    )

    # 게시글이 없는 경우
    if not posts:
        print("새로운 게시글이 없거나 목록이 비어 있습니다.")
        return

    # 첫 실행
    if first_run:
        save_seen_ids(
            {post["id"] for post in posts}
        )

        print(
            "첫 실행: 현재 게시글을 저장했습니다. "
            "알림은 보내지 않습니다."
        )

        return

    # 새 글 알림
    for post in posts:

        # URL을 찾지 못한 경우
        if not post.get("url"):
            print(
                f"URL을 찾지 못했습니다: "
                f"{post['title']} (ID: {post['id']})"
            )

        try:
            send_discord(post)

            # Discord 전송 성공한 경우에만 저장
            seen_ids.add(post["id"])

            save_seen_ids(seen_ids)

            print(
                f"Discord 알림 전송 완료: "
                f"{post['title']}"
            )

        except Exception as e:
            print(
                f"Discord 알림 전송 실패: "
                f"{post['title']}"
            )
            print(e)


if __name__ == "__main__":
    main()

