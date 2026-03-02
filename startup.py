import streamlit as st
import requests
from bs4 import BeautifulSoup, NavigableString
import re
import os
import urllib.parse
import base64
from urllib.parse import urljoin

# 보기 싫은 SSL 경고 메시지 숨기기
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================================================================================
# [1] 유틸리티 함수: 날짜 정규화
# ================================================================================
def normalize_date(date_str):
    """문자열에서 YYYY.MM.DD 형식만 추출하여 통일합니다."""
    try:
        match = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        return date_str

# ================================================================================
# [2] 연세대 창업지원단 리스트(List) 페이지 크롤링 엔진
# ================================================================================
def get_startup_links(list_url):
    """상단 고정 공지(covi-post__notice)를 제외한 일반 tr의 링크를 수집합니다."""
    links = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(list_url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        rows = soup.find_all('tr')
        
        for row in rows:
            row_classes = row.get('class', [])
            if row_classes and 'covi-post__notice' in row_classes:
                continue
                
            a_tag = row.find('a')
            if not a_tag:
                continue
                
            href = a_tag.get('href', '')
            if not href or href == '#' or 'javascript:' in href:
                continue
                
            full_url = urljoin(list_url, href)
            
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            
            num_text = "일반"
            tds = row.find_all('td')
            if tds:
                first_td_text = tds[0].get_text(strip=True)
                if first_td_text.isdigit():
                    num_text = first_td_text
                
            if not any(d['url'] == full_url for d in links):
                links.append({
                    "no": num_text,
                    "title": title,
                    "url": full_url
                })
                
        return links
        
    except Exception as e:
        st.error(f"목록을 수집하는 중 에러가 발생했습니다: {e}")
        return []

# ================================================================================
# [3] 연세대 창업지원단 상세 페이지 크롤링 엔진
# ================================================================================
def scrape_startup_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목 추출
        title = "제목 없음"
        title_tag = soup.find('h4', class_='covi-post-view__header-title')
        if title_tag:
            title = title_tag.get_text(strip=True)

        # 2. 날짜 추출
        date = "날짜 없음"
        info_div = soup.find('div', class_='covi-post-view__header-text')
        if info_div:
            date_p = info_div.find('p', attrs={'datetime': True})
            if date_p:
                date = normalize_date(date_p['datetime'])
            else:
                info_text = info_div.get_text(separator=' ', strip=True)
                date_match = re.search(r'\d{4}[-./]\d{1,2}[-./]\d{1,2}', info_text)
                if date_match:
                    date = normalize_date(date_match.group())

        # 3. 본문 및 4. 이미지 추출
        content_html = ""
        images = []
        
        content_section = soup.find('section', class_='covi-post-view__contents')
        
        if content_section:
            for idx, img in enumerate(content_section.find_all('img')):
                src = img.get('src', '')
                if not src:
                    continue
                    
                if src.startswith('data:image'):
                    try:
                        header, encoded = src.split(',', 1)
                        data = base64.b64decode(encoded)
                        ext = "png"
                        if "jpeg" in header or "jpg" in header: ext = "jpg"
                        images.append({"type": "base64", "data": data, "name": f"image_{idx+1}.{ext}"})
                    except Exception: 
                        pass
                else:
                    full_url = urljoin(url, src) 
                    parsed = urllib.parse.urlparse(full_url)
                    
                    if parsed.scheme not in ['http', 'https']:
                        img.decompose()
                        continue
                    
                    unquoted_path = urllib.parse.unquote(parsed.path)
                    encoded_path = urllib.parse.quote(unquoted_path)
                    
                    safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
                    fname = os.path.basename(unquoted_path)
                    
                    if not any(d.get('data') == safe_url for d in images):
                        images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})
                
                img.decompose()
                
            for table in content_section.find_all('table'):
                if not table.get('border'): table['border'] = "1"
            
            content_html = content_section.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        # 5. 첨부파일 추출 (★ 파일명 + 확장자 결합 로직으로 수정됨!)
        attachments = []
        files_container = soup.find('div', class_='covi-post-view__files-container')
        if files_container:
            for name_span in files_container.find_all('span', class_='covi-post-view__files-name'):
                fname = name_span.get_text(strip=True)
                
                # 바로 다음에 있는 확장자(ext) span 태그 찾기
                ext_span = name_span.find_next_sibling('span', class_='covi-post-view__files-ext')
                if ext_span:
                    fname += ext_span.get_text(strip=True) # 파일명 뒤에 .pdf 등을 바로 이어붙임
                    
                if fname and fname not in attachments:
                    attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []


# ================================================================================
# [4] UI 화면
# ================================================================================
st.set_page_config(page_title="연세 창업지원단 공지 크롤러", layout="wide")
st.title("🚀 연세대학교 창업지원단 공지사항 추출기")
st.markdown("**목록 페이지**를 입력하면 상단 고정 공지를 제외하고 모든 일반 게시물을 자동으로 긁어옵니다.")

st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: left; }
th { background-color: #f8f9fa; font-weight: bold; text-align: center; }
ul { list-style-type: disc !important; padding-left: 20px !important; }
</style>
""", unsafe_allow_html=True)

# 창업지원단 공지사항 URL
list_url_input = st.text_input("🔗 연세 창업지원단 **목록(List)** URL", value="https://venture.yonsei.ac.kr/community/notice")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        # 1. 목록에서 링크 추출
        with st.spinner("창업지원단 게시물 목록 스캔 중... (고정 공지 제외)"):
            post_links = get_startup_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 사이트 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 게시물을 발견했습니다!")
            
            # 2. 각 링크별로 상세 크롤링 수행
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"[{item['no']}] {item['title']}", expanded=True):
                    title, date, content, images, attachments = scrape_startup_detail(item['url'])
                    
                    if title:
                        st.markdown(f"### {title}")
                        st.caption(f"게시일: {date} | [원본 링크]({item['url']})")
                        
                        # 본문
                        st.markdown(content, unsafe_allow_html=True)
                        
                        # 이미지 
                        if images:
                            st.markdown(f"**🖼️ 포함된 이미지 ({len(images)}장)**")
                            cols = st.columns(min(len(images), 3) if len(images) > 0 else 1)
                            for i, img_item in enumerate(images):
                                with cols[i % 3]:
                                    try:
                                        st.image(img_item['data'], caption=img_item['name'], use_container_width=True)
                                    except Exception:
                                        pass
                        
                        # 첨부파일 (줄바꿈 나열)
                        if attachments:
                            st.markdown("**📎 첨부파일:**\n" + "\n".join([f"- {att}" for att in attachments]))
                    else:
                        st.error("내용 추출 실패")
                
                # 진행률 업데이트
                progress_bar.progress((idx + 1) / len(post_links))
            
            st.success("모든 작업이 완료되었습니다! 🎉")