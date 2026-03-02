import streamlit as st
import requests
from bs4 import BeautifulSoup
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
# [2] 연세대 총동아리연합회 리스트(List) 페이지 크롤링 엔진 (NEW)
# ================================================================================
def get_dongari_links(list_url):
    """사용자 요청 반영: notice-row(고정 공지)를 제외한 일반 bbs-list-row의 링크를 수집합니다."""
    links = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(list_url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 목록 영역 탐색
        rows = soup.find_all('div', class_='bbs-list-row')
        
        for row in rows:
            # ★ 핵심 필터: 고정 공지 클래스(notice-row) 제외
            row_classes = row.get('class', [])
            if 'notice-row' in row_classes:
                continue
                
            # 1. 링크(a 태그) 찾기
            a_tag = row.find('a')
            if not a_tag:
                continue
                
            href = a_tag.get('href', '')
            if not href or href == '#' or 'javascript:' in href:
                continue
                
            full_url = urljoin(list_url, href)
            
            # 2. 제목 추출 (a 태그 내 텍스트 또는 제목 전용 태그)
            title_elem = row.find(class_=lambda c: c and 'tit' in c)
            if title_elem and title_elem.name != 'a':
                title = title_elem.get_text(strip=True)
            else:
                title = a_tag.get_text(strip=True)
                
            if not title:
                continue
            
            # 3. 글 번호 추출
            num_elem = row.find(class_=lambda c: c and 'num' in c)
            num_text = num_elem.get_text(strip=True) if num_elem else "일반"
                
            # 중복 데이터 삽입 방지
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
# [3] 연세대 총동아리연합회 상세 페이지 크롤링 엔진
# ================================================================================
def scrape_dongari_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목 추출 (<h1 class="bbs-tit">)
        title = "제목 없음"
        title_tag = soup.find('h1', class_='bbs-tit')
        if title_tag:
            title = title_tag.get_text(strip=True)

        # 2. 날짜 추출 (<dl class="bbs-write-info"> 내에서 "등록일" 이후의 날짜)
        date = "날짜 없음"
        info_dl = soup.find('dl', class_='bbs-write-info')
        if info_dl:
            info_text = info_dl.get_text(separator=' ', strip=True)
            if '등록일' in info_text:
                date_part = info_text.split('등록일')[1]
                date_match = re.search(r'\d{4}[-./]\d{1,2}[-./]\d{1,2}', date_part)
                if date_match:
                    date = normalize_date(date_match.group())
            
            if date == "날짜 없음":
                date_match = re.search(r'\d{4}[-./]\d{1,2}[-./]\d{1,2}', info_text)
                if date_match:
                    date = normalize_date(date_match.group())

        # 3. 본문 및 4. 이미지 추출 (<div class="bbs-view-content editor">)
        content_html = ""
        images = []
        
        content_div = soup.find('div', class_='bbs-view-content')
        
        if content_div:
            for idx, img in enumerate(content_div.find_all('img')):
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
                
            for table in content_div.find_all('table'):
                if not table.get('border'): table['border'] = "1"
            
            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        # 5. 첨부파일 추출 (<dl class="bbs-file-list"> 내의 a 태그)
        attachments = []
        file_lists = soup.find_all('dl', class_='bbs-file-list')
        for fl in file_lists:
            for a_tag in fl.find_all('a'):
                href = a_tag.get('href', '')
                if href and not href.startswith('#') and 'javascript' not in href:
                    fname = a_tag.get('download') or a_tag.get_text(strip=True)
                    fname = re.sub(r'\([\d.,]+\s*(KB|MB|GB|Bytes?)\)', '', fname, flags=re.IGNORECASE).strip()
                    if fname and fname not in attachments:
                        attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []


# ================================================================================
# [4] UI 화면
# ================================================================================
st.set_page_config(page_title="총동아리연합회 공지 크롤러", layout="wide")
st.title("🎸 연세대학교 총동아리연합회 공지사항 추출기")
st.markdown("**목록 페이지**를 입력하면 상단 고정 공지(`notice-row`)를 제외하고 모든 일반 게시물을 자동으로 긁어옵니다.")

st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: left; }
th { background-color: #f8f9fa; font-weight: bold; text-align: center; }
ul { list-style-type: disc !important; padding-left: 20px !important; }
</style>
""", unsafe_allow_html=True)

# 총동아리연합회 공지사항 URL
list_url_input = st.text_input("🔗 총동아리연합회 **목록(List)** URL", value="https://dongari.yonsei.ac.kr/kr/notice/notice.php")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        # 1. 목록에서 링크 추출
        with st.spinner("게시물 목록 스캔 중... (고정 공지 제외)"):
            post_links = get_dongari_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 사이트 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 게시물을 발견했습니다!")
            
            # 2. 각 링크별로 상세 크롤링 수행
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"[{item['no']}] {item['title']}", expanded=True):
                    title, date, content, images, attachments = scrape_dongari_detail(item['url'])
                    
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