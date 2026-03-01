import streamlit as st
import requests
from bs4 import BeautifulSoup, Comment, Tag
import re
import os
import urllib.parse
import base64
from urllib.parse import urljoin

# ================================================================================
# [1] 유틸리티 함수
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
# [2] 연세 메인 리스트(List) 페이지 크롤링 엔진 (★ 스크린샷 기반 완벽 수정)
# ================================================================================
def get_yonsei_main_links(list_url):
    """
    사용자 제안 반영: '' 주석을 기점으로 고정 공지를 제외하고,
    그 아래에 있는 일반 <li> 태그 안의 <div class="num">과 <strong>을 타격합니다.
    """
    links = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        # SSL 에러 방지 및 timeout 넉넉하게 설정
        response = requests.get(list_url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. 💡 꿀팁 반영: '' 주석 찾기
        notice_end_comment = soup.find(string=lambda t: isinstance(t, Comment) and 'Notice' in t and '//' in t)
        
        items_to_parse = []
        
        if notice_end_comment:
            # 주석 이후에 등장하는 형제 노드(일반 게시물 li)들만 싹쓸이
            curr = notice_end_comment.next_sibling
            while curr:
                if isinstance(curr, Tag) and curr.name == 'li':
                    # 혹시나 남아있을 수 있는 고정공지 클래스(board-noti) 안전 필터링
                    if 'board-noti' not in curr.get('class', []):
                        items_to_parse.append(curr)
                curr = curr.next_sibling
        else:
            # 플랜 B: 만약 주석이 안 찾아지면 전체 li 중 'board-noti'가 없는 것만 추출
            for li in soup.find_all('li'):
                if 'board-noti' not in li.get('class', []):
                    items_to_parse.append(li)

        # 2. 수집된 일반 <li> 태그들을 돌며 데이터 추출
        for li in items_to_parse:
            # a 태그 (아래에 있는 요소)
            a_tag = li.find('a')
            if not a_tag or not isinstance(a_tag, Tag):
                continue
                
            href = a_tag.get('href')
            if not href or href == '#' or 'javascript:void' in href:
                continue
                
            full_url = urljoin(list_url, href)
            
            # 3. 글 번호 추출 (<div class="num">)
            num_div = a_tag.find('div', class_='num')
            if not num_div:
                continue
            num_text = num_div.get_text(strip=True)
            
            # 번호가 숫자가 아니면 찌꺼기이므로 패스
            if not num_text.isdigit():
                continue

            # 4. 글 제목 추출 (<div class="title alignL"> 안의 <strong>)
            title = "제목 없음"
            title_div = a_tag.find('div', class_=lambda c: c and 'title' in c)
            if title_div and isinstance(title_div, Tag):
                strong = title_div.find('strong')
                title = strong.get_text(strip=True) if strong else title_div.get_text(strip=True)
            else:
                title = a_tag.get_text(separator=' ', strip=True)

            # 제목 뒤에 붙는 "새글" 이라는 뱃지 텍스트 삭제
            title = title.replace('새글', '').strip()

            # 중복 데이터 삽입 방지
            if not any(d['url'] == full_url for d in links):
                links.append({
                    "no": num_text,
                    "title": title,
                    "url": full_url
                })
                
        return links
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        st.error(f"목록을 수집하는 중 에러가 발생했습니다: {e}")
        return []

# ================================================================================
# [3] 연세 메인 상세 페이지 크롤링 엔진 (기존 상세 로직 유지)
# ================================================================================
def scrape_yonsei_main_detail(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. 제목 추출 (<div class="title"> 안의 <strong>)
        title = "제목 없음"
        title_div = soup.find('div', class_='title')
        if title_div and isinstance(title_div, Tag):
            temp_soup = BeautifulSoup(str(title_div), 'html.parser')
            detail_ul = temp_soup.find('ul', class_='detail')
            if detail_ul:
                detail_ul.decompose()
                
            strong_tag = temp_soup.find('strong')
            title = strong_tag.get_text(strip=True) if strong_tag else temp_soup.get_text(strip=True)

        # 2. 작성일 추출 (<span class="needsclick">작성일</span>)
        date = "날짜 없음"
        date_span = soup.find(lambda tag: tag.name == 'span' and '작성일' in tag.get_text())
        if date_span and date_span.parent:
            raw_date_text = date_span.parent.get_text(separator=' ', strip=True).replace('작성일', '').strip()
            date = normalize_date(raw_date_text)

        # 3. 본문 및 4. 이미지 추출 (<div class="txt">)
        content_html = ""
        images = []
        
        content_div = soup.find('div', class_='txt')
        
        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all('img')):
                if not isinstance(img, Tag): continue
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
                        
                        # 한글 이미지 깨짐 완벽 방지
                        unquoted_path = urllib.parse.unquote(parsed.path)
                        encoded_path = urllib.parse.quote(unquoted_path)
                        
                        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
                        fname = os.path.basename(unquoted_path)
                        
                        if not any(d.get('data') == safe_url for d in images):
                            images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})
                
                img.decompose()
                
            for table in content_div.find_all('table'):
                if isinstance(table, Tag) and not table.get('border'): table['border'] = "1"
            
            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        # 5. 첨부파일 추출 (<div class="attachment">)
        attachments = []
        attach_div = soup.find('div', class_='attachment')
        if attach_div and isinstance(attach_div, Tag):
            for a_tag in attach_div.find_all('a'):
                fname = a_tag.get_text(strip=True)
                if fname and fname not in attachments:
                    attachments.append(fname)

        return title, date, content_html, images, attachments

    except Exception as e:
        return None, f"에러: {e}", "", [], []


# ================================================================================
# [4] UI 화면
# ================================================================================
st.set_page_config(page_title="연세대 메인 공지 크롤러", layout="wide")
st.title("🦅 연세대학교 메인 공지사항 추출기")
st.markdown("**목록 페이지**를 입력하면, 상단 일반공지를 제외한 **숫자 번호가 있는 일반 게시물**을 자동으로 긁어옵니다.")

st.markdown("""
<style>
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
th, td { border: 1px solid #ddd !important; padding: 8px; text-align: left; }
th { background-color: #f8f9fa; font-weight: bold; text-align: center; }
ul { list-style-type: disc !important; padding-left: 20px !important; }
</style>
""", unsafe_allow_html=True)

# 연세 메인 공지사항 URL
list_url_input = st.text_input("🔗 연세대 메인 공지사항 **목록(List)** URL", value="https://www.yonsei.ac.kr/sc/254/subview.do")

if st.button("최신 공지사항 긁어오기", type="primary"):
    if not list_url_input:
        st.warning("목록 URL을 입력해주세요.")
    else:
        with st.spinner("연세대 메인 공지 목록 스캔 중... (일반공지 제외)"):
            post_links = get_yonsei_main_links(list_url_input)
        
        if not post_links:
            st.error("게시물을 찾을 수 없습니다. URL을 확인하거나 사이트 구조가 변경되었는지 확인해주세요.")
        else:
            st.success(f"총 {len(post_links)}개의 일반 게시물을 발견했습니다!")
            
            progress_bar = st.progress(0)
            
            for idx, item in enumerate(post_links):
                with st.expander(f"#{item['no']} {item['title']}", expanded=True):
                    title, date, content, images, attachments = scrape_yonsei_main_detail(item['url'])
                    
                    if title:
                        st.markdown(f"### {title}")
                        st.caption(f"게시일: {date} | [원본 링크]({item['url']})")
                        
                        st.markdown(content, unsafe_allow_html=True)
                        
                        if images:
                            st.markdown(f"**🖼️ 포함된 이미지 ({len(images)}장)**")
                            cols = st.columns(min(len(images), 3) if len(images) > 0 else 1)
                            for i, img_item in enumerate(images):
                                with cols[i % 3]:
                                    st.image(img_item['data'], caption=img_item['name'], use_container_width=True)
                        
                        if attachments:
                            st.markdown("**📎 첨부파일:**\n" + "\n".join([f"- {att}" for att in attachments]))
                    else:
                        st.error("내용 추출 실패")
                
                progress_bar.progress((idx + 1) / len(post_links))
            
            st.success("모든 작업이 완료되었습니다! 🎉")