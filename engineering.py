import streamlit as st
import requests
from bs4 import BeautifulSoup, NavigableString, Tag, Comment
import base64
import re
import os
from urllib.parse import urljoin

# --- 페이지 설정 ---
st.set_page_config(page_title="연세 공학 공지 리스트 크롤러", layout="wide")
st.title("🦅 연세 공학 공지사항 리스트 추출기")
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

# --------------------------------------------------------------------------------
# [1] 기존 상세 페이지 크롤링 로직 (주석 무시 로직 추가)
# --------------------------------------------------------------------------------
def process_table_html(table_tag):
    for tag in table_tag(['script', 'style', 'noscript', 'iframe']):
        tag.decompose()
    if not table_tag.get('border'):
        table_tag['border'] = "1"
    return str(table_tag)

def get_text_structurally(element):
    # ★ 버그 수정: HTML 주석(Comment)인 경우 텍스트로 취급하지 않고 빈 문자열 반환
    if isinstance(element, Comment):
        return ""
        
    text_content = ""
    if isinstance(element, NavigableString):
        return str(element)
    if element.name == 'table':
        return process_table_html(element)
        
    for child in element.children:
        # ★ 버그 수정: 자식 노드 탐색 시에도 주석이면 건너뜀
        if isinstance(child, Comment): 
            continue
        if child.name in ['script', 'style', 'noscript']: continue
        if child.name == 'br':
            text_content += '\n'
            continue
            
        child_text = get_text_structurally(child)
        block_tags = ['div', 'p', 'li', 'tr', 'h1', 'h2', 'h3', 'option', 'dd', 'dt']
        if child.name in block_tags:
            if child_text.strip() or "<table" in child_text:
                text_content += "\n" + child_text.strip() + "\n"
        else:
            text_content += child_text
    return text_content

def finalize_text(text):
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()

def scrape_yonsei_engineering_precise(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None, "접속 실패", None, [], []

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 제목
        title = "제목 없음"
        title_label = soup.find(string=lambda t: t and "제목" in t)
        if title_label:
            title_container = title_label.find_parent(['dt', 'th', 'td'])
            if title_container:
                title_elem = title_container.find_next_sibling(['dd', 'td'])
                if title_elem:
                    title = get_text_structurally(title_elem).strip()
        if title == "제목 없음":
            h3 = soup.find('h3')
            if h3: title = get_text_structurally(h3).strip()

        # 게시일
        date = "날짜 없음"
        date_match = re.search(r'\d{4}[.-]\d{2}[.-]\d{2}', soup.get_text())
        if date_match: date = date_match.group()

        # 본문 (정밀 타격)
        content_text = ""
        main_container = None
        anchor_text = soup.find(string=lambda t: t and "게시글 내용" in t)
        if anchor_text:
            start_tag = anchor_text.find_parent(['dt', 'th', 'td'])
            if start_tag:
                target_body = start_tag.find_next_sibling(['dd', 'td'])
                if target_body:
                    main_container = target_body
                    garbage_selectors = ['.btn_area', '.btn-wrap', '#bo_v_share', 'ul.btn_bo_user', 'div.btn_confirm']
                    for selector in garbage_selectors:
                        for tag in main_container.select(selector):
                            tag.decompose()
                    raw_text = get_text_structurally(main_container)
                    stop_keywords = ["관리자 if문", "답변글 버튼", "목록 List 버튼", "등록 버튼"]
                    for keyword in stop_keywords:
                        if keyword in raw_text:
                            raw_text = raw_text.split(keyword)[0]
                    content_text = finalize_text(raw_text)

        if not content_text:
            content_text = "(본문 영역인 <dd> 태그를 찾지 못했습니다.)"

        # 이미지
        images_data = []
        if main_container:
            img_tags = main_container.find_all('img')
            for idx, img in enumerate(img_tags):
                src = img.get('src', '')
                if not src: continue
                if src.startswith('data:image'):
                    try:
                        header, encoded = src.split(',', 1)
                        data = base64.b64decode(encoded)
                        ext = "png"
                        if "jpeg" in header or "jpg" in header: ext = "jpg"
                        images_data.append({"type": "base64", "data": data, "ext": ext, "name": f"image_{idx+1}.{ext}"})
                    except: continue
                else:
                    if any(x in src for x in ['icon', 'btn', 'button', 'search', 'blank']): continue
                    if src.startswith('/'): full_url = 'https://engineering.yonsei.ac.kr' + src
                    elif src.startswith('http'): full_url = src
                    else: continue
                    if any(d['data'] == full_url for d in images_data if d['type'] == 'url'): continue
                    file_name = img.get('data-file_name') or os.path.basename(src.split('?')[0])
                    if not file_name or '.' not in file_name: file_name = f"image_{idx+1}.jpg"
                    images_data.append({"type": "url", "data": full_url, "ext": file_name.split('.')[-1], "name": file_name})

        # 첨부파일
        attachment_names = []
        attach_labels = soup.find_all(string=re.compile("첨부"))
        for label in attach_labels:
            parent_row = label.find_parent(['tr', 'li', 'div', 'dl', 'dt', 'dd'])
            if parent_row and parent_row.name == 'dt':
                parent_row = parent_row.find_next_sibling('dd')
            if parent_row:
                links = parent_row.find_all('a')
                for link in links:
                    file_name = link.get_text(strip=True)
                    href = link.get('href', '')
                    if href and not href.startswith('#') and 'javascript' not in href:
                         if file_name and file_name not in attachment_names:
                             attachment_names.append(file_name)

        return title, date, content_text, images_data, attachment_names

    except Exception as e:
        return None, f"에러: {e}", None, [], []

# --------------------------------------------------------------------------------
# [2] 리스트 페이지 크롤러
# --------------------------------------------------------------------------------
def get_notice_links(list_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(list_url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = []
        rows = soup.select('tbody tr')
        
        for row in rows:
            cols = row.find_all('td')
            if not cols: continue
            
            num_text = cols[0].get_text(strip=True)
            if num_text.isdigit():
                link_tag = row.find('a')
                if link_tag and link_tag.get('href'):
                    full_url = urljoin(list_url, link_tag['href'])
                    links.append({
                        "no": num_text,
                        "url": full_url
                    })
                    
        return links

    except Exception as e:
        st.error(f"리스트 페이지 분석 실패: {e}")
        return []

# --- UI 화면 ---
list_url_input = st.text_input("🔗 공지사항 **목록(List)** URL", placeholder="https://engineering.yonsei.ac.kr/engineering/notice.do")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        with st.spinner('게시물 목록 스캔 중... (고정 공지는 제외합니다)'):
            post_links = get_notice_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 게시판 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 일반 게시물을 발견했습니다!")
            
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"#{item['no']}번 게시물 크롤링 중...", expanded=True):
                    title, date, content, images, attachments = scrape_yonsei_engineering_precise(item['url'])
                    
                    if title:
                        st.markdown(f"### [{item['no']}] {title}")
                        st.caption(f"게시일: {date} | [원본 링크]({item['url']})")
                        
                        st.markdown(content, unsafe_allow_html=True)
                        
                        if images:
                            st.markdown(f"**🖼️ 포함된 이미지 ({len(images)}장)**")
                            cols = st.columns(min(len(images), 3))
                            for i, img_item in enumerate(images):
                                with cols[i % 3]:
                                    if img_item['type'] == 'base64':
                                        st.image(img_item['data'], use_container_width=True)
                                    else:
                                        st.image(img_item['data'], use_container_width=True)
                        
                        if attachments:
                            st.markdown(f"**📎 첨부파일: {', '.join(attachments)}**")
                    else:
                        st.error("내용 추출 실패")
                
                progress_bar.progress((idx + 1) / len(post_links))
            
            st.success("모든 작업이 완료되었습니다! 🎉")