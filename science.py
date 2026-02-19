import streamlit as st
import requests
from bs4 import BeautifulSoup, Comment
import re
import os
import urllib.parse
import base64
from urllib.parse import urljoin

# ================================================================================
# [1] 기존 이과대학 상세 크롤링 로직 (절대 수정 안 함, 원본 그대로)
# ================================================================================
def normalize_date(date_str):
    try:
        match = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except:
        return date_str

def get_body_soup(soup):
    start_node = soup.find(string=lambda text: isinstance(text, Comment) and "게시물 내용" in text and "//" not in text)
    if not start_node: return None
        
    end_comment = soup.find(string=lambda text: isinstance(text, Comment) and "// 게시물 내용" in text)
    
    temp_html = ""
    curr = start_node.next_sibling
    while curr and curr != end_comment:
        temp_html += str(curr)
        curr = curr.next_sibling
        
    temp_soup = BeautifulSoup(temp_html, 'html.parser')
    
    files_div = temp_soup.find('div', class_='nxb-view__files')
    if files_div:
        for element in files_div.find_all_next():
            element.extract()
        files_div.extract()
        
    return temp_soup

def scrape_science_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = "제목 없음"
        t_tag = soup.find('h3', class_='nxb-view__header-title')
        if t_tag: title = t_tag.get_text(strip=True)

        date = "날짜 없음"
        dt_tags = soup.find_all('div', class_='nxb-view__info-dt')
        for dt in dt_tags:
            if '작성일' in dt.get_text():
                dd = dt.find_next_sibling('div', class_='nxb-view__info-dd')
                if dd:
                    date = normalize_date(dd.get_text(strip=True))
                    break

        content_html = ""
        images = []
        
        temp_soup = get_body_soup(soup)
        if temp_soup:
            for idx, img in enumerate(temp_soup.find_all('img')):
                src = img.get('src', '')
                if src and not any(x in src for x in ['icon', 'btn', 'blank']):
                    if src.startswith('data:image'):
                        try:
                            header, encoded = src.split(',', 1)
                            data = base64.b64decode(encoded)
                            ext = "png"
                            if "jpeg" in header or "jpg" in header: ext = "jpg"
                            images.append({"type": "base64", "data": data, "name": f"image_{idx+1}.{ext}"})
                        except Exception: pass
                    else:
                        full_url = urljoin(url, src) 
                        parsed = urllib.parse.urlparse(full_url)
                        encoded_path = urllib.parse.quote(parsed.path)
                        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
                        fname = os.path.basename(parsed.path)
                        if not any(d.get('data') == safe_url for d in images):
                            images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})
                img.decompose()
                
            for table in temp_soup.find_all('table'):
                if not table.get('border'): table['border'] = "1"
            content_html = temp_soup.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        attachments = []
        file_divs = soup.find_all('div', class_='file-name-area')
        for fdiv in file_divs:
            fname = "".join([node for node in fdiv.contents if isinstance(node, str)]).strip()
            if fname and fname not in attachments:
                attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []

# ================================================================================
# [2] 이과대학 리스트 페이지 크롤러 (절대 수정 안 함, 원본 그대로)
# ================================================================================
def get_science_links(url):
    links = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        rows = soup.select('.nxb-list-table tbody tr')
        for row in rows:
            num_td = row.find('td', class_='nxb-list-table__num')
            if not num_td: continue

            if num_td.find('i', class_='nxb-list-table__notice-icon'):
                continue

            num = num_td.get_text(strip=True)
            if not num.isdigit(): continue

            title_td = row.find('td', class_='nxb-list-table__title')
            if title_td:
                a_tag = title_td.find('a')
                if a_tag:
                    href = a_tag.get('href')
                    full_url = urljoin(url, href)
                    links.append({
                        "no": num,
                        "title": a_tag.get_text(strip=True),
                        "url": full_url
                    })
        return links
    except Exception as e:
        print(f"목록 수집 에러: {e}")
        return []


# ================================================================================
# [3] UI 화면 (공대 engineering.py와 완벽히 동일한 UI 구조 + 첨부파일 줄바꿈)
# ================================================================================
st.set_page_config(page_title="연세 이과대학 공지 리스트 크롤러", layout="wide")
st.title("🔬 연세 이과대학 공지사항 리스트 추출기")
st.markdown("**목록 페이지**를 입력하면, 상단 고정 공지를 제외한 **최신 일반 게시물(번호 있는 것)**을 자동으로 긁어옵니다.")

# --- [스타일] 표 스타일 보정 ---
st.markdown("""
<style>
table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 20px;
}
th, td {
    border: 1px solid #ddd !important;
    padding: 8px;
    text-align: center;
}
th {
    background-color: #f8f9fa;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# 제대로 된 URL을 기본값으로 설정
list_url_input = st.text_input("🔗 공지사항 **목록(List)** URL", value="http://science.yonsei.ac.kr/community/notice")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        # 1. 목록에서 링크 추출
        with st.spinner('게시물 목록 스캔 중... (고정 공지는 제외합니다)'):
            post_links = get_science_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 게시판 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 일반 게시물을 발견했습니다!")
            
            # 2. 각 링크별로 상세 크롤링 수행 (Progress bar 적용)
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                # Expander 창으로 깔끔하게 정리
                with st.expander(f"#{item['no']}번 게시물 크롤링 중...", expanded=True):
                    # 이과대학 전용 상세 크롤링 함수 호출
                    title, date, content, images, attachments = scrape_science_detail(item['url'])
                    
                    if title:
                        st.markdown(f"### [{item['no']}] {title}")
                        st.caption(f"게시일: {date} | [원본 링크]({item['url']})")
                        
                        # 본문 (HTML 표 지원)
                        st.markdown(content, unsafe_allow_html=True)
                        
                        # 이미지
                        if images:
                            st.markdown(f"**🖼️ 포함된 이미지 ({len(images)}장)**")
                            cols = st.columns(min(len(images), 3) if len(images) > 0 else 1)
                            for i, img_item in enumerate(images):
                                with cols[i % 3]:
                                    st.image(img_item['data'], caption=img_item['name'], use_container_width=True)
                        
                        # 첨부파일 (줄바꿈 나열로 변경)
                        if attachments:
                            st.markdown("**📎 첨부파일:**\n" + "\n".join([f"- {att}" for att in attachments]))
                    else:
                        st.error("내용 추출 실패")
                
                # 진행률 업데이트
                progress_bar.progress((idx + 1) / len(post_links))
            
            st.success("모든 작업이 완료되었습니다! 🎉")