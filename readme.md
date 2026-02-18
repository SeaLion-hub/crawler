

# 🦅 연세대학교 공지사항 크롤러 모듈 (Yonsei Notice Crawler)

이 저장소는 연세대학교의 여러 단과대학 공지사항을 수집하는 **독립형 파이썬 모듈 모음**입니다.
각 단과대학의 홈페이지 구조(CMS)가 다르기 때문에, 반드시 **학과에 맞는 모듈을 import** 하여 사용해야 합니다.

---

## 📂 1. 모듈별 지원 대학 및 특징

이식하려는 단과대학에 맞춰 아래 파일을 사용하세요.

### **1) `crawler_engineering.py` (공학 계열)**

* **적용 가능 대학:** 공과대학, 학부대학, 약학대학, 상경대학
* **주요 특징:**
* 목록에서 '공지' 텍스트가 있는 고정 게시물을 제외하고 **번호가 있는 최신글**만 수집.
* 상세 페이지에서 `'게시글 내용'` 텍스트 옆의 `<dd>` 태그를 찾아 본문을 추출.
* 관리자용 버튼이나 불필요한 UI 요소 자동 제거.



### **2) `crawler_medicine.py` (의학 계열)**

* **적용 가능 대학:** 의과대학, 치과대학
* **주요 특징:**
* 목록에서 `bbs-item` 클래스를 감지하여 게시물 리스트만 정확히 추출.
* 상세 페이지에서 `.fr-view` 클래스를 기준으로 본문 추출.
* 본문 하단의 검색엔진용 주석(``) 이후 내용을 잘라냄.



### **3) `crawler_ai.py` (인공지능 계열)**

* **적용 가능 대학:** 인공지능융합대학
* **주요 특징:**
* 그누보드(GnuBoard) 기반 사이트 대응.
* HTML 내부의 `` 주석을 찾아 정밀하게 추출.



### **4) `crawler_business.py` (경영 계열)**

* **적용 가능 대학:** 경영대학
* **주요 특징:**
* **인코딩 보정:** `CP949(EUC-KR)` 인코딩을 자동 감지하여 한글 깨짐 방지.
* 목록에서 `<td class="Subject">`를 타격하여 링크 수집.
* 첨부파일이 `.asp` 다운로드 링크 형태인 경우 대응.



---

## ⚠️ 이식 시 절대 주의사항 (Critical Warnings)

앱 서버에 이식할 때 아래 **3가지 규칙**을 반드시 지켜주세요.

### **1. 실제 URL 파라미터 주입 필수**

크롤러 함수는 URL을 인자로 받도록 설계되어 있습니다. 함수를 호출할 때 **해당 학과의 실제 공지사항 목록 URL**을 넘겨줘야 합니다.

* **잘못된 예:** `get_engineering_links()` (인자 없음)
* **올바른 예:** `get_engineering_links("https://engineering.yonsei.ac.kr/engineering/notice.do")`

### **2. 추출 로직 수정 금지**

각 파일의 `scrape_detail` 함수 내부 로직은 수많은 예외 처리가 되어 있습니다.

* **`label_sibling` 로직 (공대):** 라벨 옆의 태그를 찾는 방식은 절대 바꾸지 마세요.
* **`fr-view` 및 주석 처리 (의대):** 이를 삭제하면 불필요한 메뉴나 검색어까지 크롤링 됩니다.
* **HTML 표 보존:** `<table>` 태그를 Markdown이나 텍스트로 변환하지 마세요. (시간표, 커리큘럼 표 깨짐 방지)

### **3. 반환된 본문은 HTML 뷰어로 표시**

크롤러가 반환하는 `content` 데이터는 **HTML 태그(`<table>`, `<ul>`, `<strong>` 등)가 포함**되어 있습니다.

* 앱 클라이언트에서 이를 보여줄 때는 **WebView**나 **HTML 렌더링 컴포넌트**를 사용해야 표와 서식이 깨지지 않습니다.

---

## 🚀 설치 및 사용 예시

### **필요 라이브러리**

```bash
pip install requests beautifulsoup4

```

### **사용 코드 예시**

**예시 1: 공과대학 크롤링**

```python
import crawler_engineering as crawler

# 1. 목록 URL 설정 (실제 사이트 주소)
target_url = "https://engineering.yonsei.ac.kr/engineering/notice.do"

# 2. 목록 가져오기
links = crawler.get_engineering_links(target_url)

# 3. 상세 내용 크롤링
for post in links:
    print(f"번호: {post['no']}")
    # 반환값: 제목, 날짜, 본문(HTML), 이미지리스트, 첨부파일리스트
    title, date, content, imgs, files = crawler.scrape_engineering_detail(post['url'])

```

**예시 2: 의과대학 크롤링**

```python
import crawler_medicine as crawler

target_url = "https://medicine.yonsei.ac.kr/medicine/news/notice.do"
links = crawler.get_medicine_notice_links(target_url)

for post in links:
    title, date, content, imgs, files = crawler.scrape_medicine_detail(post['url'])

```

---

## 🛠️ 데이터 반환 구조 (Data Structure)

모든 상세 크롤링 함수는 다음과 같은 순서의 **튜플(Tuple)**을 반환합니다.

1. **`title` (String):** 게시물 제목
2. **`date` (String):** `YYYY.MM.DD` 형식으로 통일된 날짜
3. **`content` (String):** HTML 태그가 살아있는 본문 텍스트
4. **`images` (List):** 본문 내 이미지 정보 리스트
* 형식: `[{ "type": "url", "data": "이미지주소", "name": "파일명.jpg" }, ...]`


5. **`attachments` (List):** 첨부파일 다운로드 링크 또는 파일명 리스트