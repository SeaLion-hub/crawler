import streamlit as st
import requests
from bs4 import BeautifulSoup, NavigableString, Comment, Tag
import base64
import re
import os
from urllib.parse import urljoin

# --- 페이지 설정 ---
st.set_page_config(page_title="인공지능융합대학 통합 크롤러", layout="wide")
st.title("🦅 인공지능융합대학 공지사항 추출기 (목록+상세)")
st.markdown("목록에서 **'공지' 제외, 번호 게시물**만 자동 수집하여 상세 내용을 긁어옵니다.")

# --- [스타일] 표/이미지 스타일 ---
st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: center; }
th { background-color: #f8f9fa; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# [1] 상세 페이지 크롤링 엔진 (주석 타격 + 표 보존 + 날짜 통일)
# ==============================================================================

def normalize_date(date_str):
    """날짜를 YYYY.MM.DD 형식으로 통일"""
    try:
        clean_str = re.sub(r'[년월일/-]', '.', date_str)
        parts = [p.strip() for p in clean_str.split('.') if p.strip().isdigit()]
        if len(parts) >= 3:
            y, m, d = parts[:3]
            if len(y) == 2: y = "20" + y
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except: return date_str

def process_table_html(table_tag):
    for tag in table_tag(['script', 'style', 'noscript', 'iframe']): tag.decompose()
    if not table_tag.get('border'): table_tag['border'] = "1"
    return str(table_tag)

def get_text_structurally(element):
    if isinstance(element, NavigableString): return str(element)
    if element.name == 'table': return process_table_html(element)
    
    text = ""
    for child in element.children:
        if child.name in ['script', 'style', 'noscript']: continue
        if isinstance(child, Comment): continue
        if child.name == 'br': 
            text += '\n'
            continue
        
        child_text = get_text_structurally(child)
        if child.name in ['div', 'p', 'li', 'dd', 'dt', 'tr', 'h1', 'h2', 'h3']:
            if child_text.strip() or "<table" in child_text:
                text += "\n" + child_text.strip() + "\n"
        else:
            text += child_text
    return text

def extract_between_comments(soup, start_keyword, end_keyword):
    start_comment = soup.find(string=lambda t: isinstance(t, Comment) and start_keyword in t)
    if not start_comment: return None

    tags = []
    curr = start_comment.next_sibling
    while curr:
        if isinstance(curr, Comment) and end_keyword in curr: break
        if isinstance(curr, Tag) or (isinstance(curr, NavigableString) and curr.strip()):
            tags.append(curr)
        curr = curr.next_sibling
    return tags

def scrape_computing_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목
        title = "제목 없음"
        title_elem = soup.find(id="bo_v_title") or soup.find(class_="bo_v_title")
        if title_elem: title = title_elem.get_text(strip=True)

        # 2. 날짜 (보통 bo_v_info 안에 있음)
        date = "날짜 없음"
        info_sec = soup.find(id="bo_v_info") or soup
        date_match = re.search(r'\d{2,4}\s*[.-]\s*\d{1,2}\s*[.-]\s*\d{1,2}', info_sec.get_text())
        if date_match: date = normalize_date(date_match.group())

        # 3. 본문 (주석 타격)
        content_text = ""
        images = []
        
        # '본문 내용 시작' ~ '본문 내용 끝' 주석 사이 추출
        body_tags = extract_between_comments(soup, "본문 내용 시작", "본문 내용 끝")
        
        if body_tags:
            temp_soup = BeautifulSoup("", 'html.parser')
            for t in body_tags: temp_soup.append(t)
            
            content_text = get_text_structurally(temp_soup)
            content_text = re.sub(r'\n\s*\n+', '\n\n', content_text).strip()
            
            # 이미지
            for img in temp_soup.find_all('img'):
                src = img.get('src', '')
                if not src: continue
                if src.startswith('data:image'): pass # 생략
                else:
                    if any(x in src for x in ['icon', 'btn', 'blank']): continue
                    # 그누보드는 보통 절대경로거나 /data/.. 형태
                    if src.startswith('/'): full = "https://computing.yonsei.ac.kr" + src
                    else: full = src
                    
                    fname = os.path.basename(full.split('?')[0])
                    if not fname or '.' not in fname: fname = "image.jpg"
                    
                    if not any(d['data'] == full for d in images):
                        images.append({"type": "url", "data": full, "name": fname})
        else:
            content_text = "(본문을 찾을 수 없습니다)"

        # 4. 첨부파일 (주석 타격)
        attachments = []
        file_tags = extract_between_comments(soup, "첨부파일 시작", "첨부파일 끝")
        if file_tags:
            for t in file_tags:
                if isinstance(t, Tag):
                    for a in t.find_all('a'):
                        # 그누보드 다운로드 링크 특징
                        if 'download.php' in a.get('href', ''):
                            fname = a.get_text(strip=True)
                            if fname and fname not in attachments:
                                attachments.append(fname)
                                
        return title, date, content_text, images, attachments

    except Exception as e:
        return None, f"에러: {e}", None, [], []


# ==============================================================================
# [2] 목록(List) 크롤링 엔진 (NEW)
# ==============================================================================

def get_computing_notice_links(list_url):
    """
    그누보드 게시판 목록에서 '공지'를 제외하고 '번호'가 있는 게시물의 링크를 추출합니다.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(list_url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = []
        
        # 그누보드 게시판은 보통 tbl_head01 클래스나 그냥 tbody 안의 tr을 씁니다.
        rows = soup.select('tbody tr')
        
        for row in rows:
            cols = row.find_all('td')
            if not cols: continue
            
            # 첫 번째 컬럼: 번호 (td_num)
            # 공지사항은 여기에 '공지'라고 써있거나 strong 태그가 있음
            num_text = cols[0].get_text(strip=True)
            
            # ★ 핵심 필터: 숫자인지 확인 (공지, Notice 등은 걸러짐)
            if num_text.isdigit():
                # 제목 컬럼 찾기 (보통 'td_subject' 클래스를 가짐)
                subject_td = row.find('td', class_='td_subject')
                if not subject_td:
                    # 클래스가 없으면 두 번째(1번 인덱스) 컬럼을 제목으로 가정
                    if len(cols) > 1: subject_td = cols[1]
                
                if subject_td:
                    link_tag = subject_td.find('a')
                    if link_tag and link_tag.get('href'):
                        # 링크 추출
                        full_url = link_tag['href'] 
                        # 만약 상대경로라면 변환 (그누보드는 보통 절대경로를 줌)
                        if not full_url.startswith('http'):
                            full_url = urljoin(list_url, full_url)
                            
                        links.append({
                            "no": num_text,
                            "url": full_url
                        })

        return links

    except Exception as e:
        st.error(f"목록 분석 실패: {e}")
        return []

# ==============================================================================
# [3] UI 실행
# ==============================================================================

list_url_input = st.text_input("🔗 인공지능융합대학 공지 목록 URL", 
                               value="https://computing.yonsei.ac.kr/bbs/board.php?bo_table=sub4_4")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("URL을 입력해주세요.")
    else:
        with st.spinner('목록 스캔 중... (공지 제외, 번호 게시물만 수집)'):
            post_links = get_computing_notice_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. (URL 확인 또는 사이트 구조 변경)")
        else:
            st.success(f"총 {len(post_links)}개의 최신 게시물을 찾았습니다!")
            
            progress = st.progress(0)
            for idx, post in enumerate(post_links):
                with st.expander(f"#{post['no']}번 게시물 가져오는 중...", expanded=True):
                    t, d, c, i, a = scrape_computing_detail(post['url'])
                    
                    if t:
                        st.markdown(f"### [{post['no']}] {t}")
                        st.caption(f"게시일: {d} | [원본 링크]({post['url']})")
                        st.markdown(c, unsafe_allow_html=True) # 표 렌더링
                        
                        if i:
                            st.markdown(f"**이미지 ({len(i)}장)**")
                            cols = st.columns(min(len(i), 3))
                            for k, img in enumerate(i):
                                with cols[k%3]:
                                    st.image(img['data'], use_container_width=True)
                        if a:
                            st.markdown(f"**첨부파일:** {', '.join(a)}")
                    else:
                        st.error("상세 내용을 가져오지 못했습니다.")
                
                progress.progress((idx + 1) / len(post_links))
            
            st.success("모든 작업 완료!")