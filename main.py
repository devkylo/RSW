import os
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import timedelta, datetime
import time
import pytz
import json
from st_aggrid import AgGrid, GridOptionsBuilder
from collections import defaultdict
from urllib.parse import unquote
from cryptography.fernet import Fernet

korea_tz = pytz.timezone("Asia/Seoul")
today_date = datetime.now(korea_tz)
current_year = today_date.year
current_month = today_date.month

# ------------------------------------------------------------------------------
# 1) GitHub 초기화 모듈
# ------------------------------------------------------------------------------
def git_init_repo():
    """Git 저장소 초기화 및 원격 연결"""
    if not os.path.exists(schedules_root_dir):
        os.makedirs(schedules_root_dir, exist_ok=True)
        os.system(f'cd {schedules_root_dir} && git init')
        os.system(f'cd {schedules_root_dir} && git remote add origin {st.secrets["GITHUB"]["REPO_URL"]}')

def git_auto_commit(file_path, team_name):
    """변경사항 자동 커밋"""
    commit_message = f"Auto-commit: {team_name} {datetime.now(korea_tz).strftime('%Y-%m-%d %H:%M')}"
    os.system(f'cd {schedules_root_dir} && git add {file_path}')
    os.system(f'cd {schedules_root_dir} && git commit -m "{commit_message}"')
    os.system(f'cd {schedules_root_dir} && git push origin main')

def git_pull_changes():
    """최신 변경사항 동기화"""
    os.system(f'cd {schedules_root_dir} && git pull origin main')

def handle_git_conflicts():
    """충돌 자동 해결"""
    conflicts = os.popen(f'cd {schedules_root_dir} && git diff --name-only --diff-filter=U').read()
    if conflicts:
        st.warning("충돌 감지! 자동 해결 시도 중...")
        os.system(f'cd {schedules_root_dir} && git checkout --theirs .')
        git_auto_commit(conflicts, "Conflict Resolution")
        st.rerun()

def encrypt_data(data):
    """데이터 암호화 예시 함수"""
    cipher = Fernet(st.secrets["CRYPTO"]["KEY"])
    return cipher.encrypt(data.encode())

# ------------------------------------------------------------------------------
# 2) 디렉토리 생성 로직
# ------------------------------------------------------------------------------
schedules_root_dir = "team_schedules"
model_example_root_dir = "team_model_example"
today_schedules_root_dir = "team_today_schedules" # 매일 근무자 dir 생성
memo_root_dir = "team_memo"

# GitHub 저장소 초기화 (최상단에서 1회 실행)
git_init_repo()
git_pull_changes()

def create_dir_safe(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        st.toast(f"{path} 디렉토리 생성 완료", icon="📂")

for d in [schedules_root_dir, model_example_root_dir, today_schedules_root_dir, memo_root_dir]:
    create_dir_safe(d)

# 앱 시작 시 최초 동기화
if 'git_synced' not in st.session_state:
    git_pull_changes()
    st.session_state.git_synced = True

# 30분 단위 실시간 동기화
if (datetime.now() - st.session_state.get('last_sync', datetime.now())).seconds > 600:
    git_pull_changes()
    st.session_state.last_sync = datetime.now()
    #st.toast("GitHub에서 최신 데이터 동기화 완료!", icon="🔄")

st.title("Rotation Scheduler WebService 💻")

st.sidebar.title("팀 선택 ✅")
teams = ["관제SO팀", "동부SO팀", "보라매SO팀", "백본SO팀", "보안SO팀", "성수SO팀", "중부SO팀"]
selected_team = st.sidebar.radio("", teams)

months = [f"{i}월" for i in range(1, 13)]

# 날짜와 월 선택 동기화 적용
# 초기화: 세션 상태에 기본값 설정
if "selected_date" not in st.session_state:
    st.session_state["selected_date"] = today_date.date()

if "selected_month" not in st.session_state:
    st.session_state["selected_month"] = f"{today_date.month}월"

def update_date_from_month():
    new_month_num = int(st.session_state["selected_month"].replace("월", ""))
    
    # selected_date가 없을 때만, 현재 st.session_state["selected_month"] 기준으로 기본값 세팅
    #if "selected_date" not in st.session_state:
        #st.session_state["selected_date"] = datetime(current_year, new_month_num, 1).date()

    #try:
        #orig_day = st.session_state["selected_date"].day
        #st.session_state["selected_date"] = datetime(current_year, new_month_num, orig_day).date()
    #except ValueError:
        # orig_day가 해당 월에 없으면 1일로 맞춤
    st.session_state["selected_date"] = datetime(current_year, new_month_num, 1).date()

def update_month_from_date():
    st.session_state["selected_month"] = f"{st.session_state['selected_date'].month}월"

st.sidebar.title("월 선택 📅")
st.sidebar.selectbox(
    "",
    options=months,
    key="selected_month",
    on_change=update_date_from_month
)

schedules_folder_path = os.path.join(schedules_root_dir, selected_team)
model_example_folder_path = os.path.join(model_example_root_dir, selected_team)
today_team_folder_path = os.path.join(today_schedules_root_dir, selected_team)
memo_team_folder_path = os.path.join(memo_root_dir, selected_team)

create_dir_safe(schedules_folder_path)
create_dir_safe(model_example_folder_path)
create_dir_safe(today_team_folder_path)
create_dir_safe(memo_team_folder_path)

selected_month_num = int(st.session_state["selected_month"].replace("월", ""))

start_date = datetime(current_year, selected_month_num, 1)
end_date = (start_date + timedelta(days=31)).replace(day=1) - timedelta(days=1)
date_list = [(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)]

schedules_file_path = os.path.join(schedules_folder_path, f"{current_year}_{st.session_state['selected_month']}_{selected_team}_schedule.csv")
model_example_file_path = os.path.join(model_example_folder_path, f"{selected_team}_model_example.csv")
memo_file_path = os.path.join(memo_team_folder_path, f"{current_year}_{st.session_state['selected_month']}_memos.json")

st.sidebar.title("메모 추가 ✏️")

if 'new_memo_text' not in st.session_state:
    st.session_state.new_memo_text = ""

if 'author_name' not in st.session_state:
    st.session_state.author_name = ""

def get_korea_time():
    return datetime.now(korea_tz).strftime('%Y-%m-%d %H:%M:%S')

def save_memo_with_reset(memo_file_path, memo_text, author=""):
    memo_data = {
        "note": memo_text,
        "author": author,
        "timestamp": get_korea_time()
    }
    if os.path.exists(memo_file_path):
        with open(memo_file_path, "r", encoding="utf-8") as f:
            memos_list = json.load(f)
    else:
        memos_list = []

    for existing_memo in memos_list:
        if (existing_memo["note"] == memo_data["note"] and
            existing_memo["author"] == memo_data["author"] and
            existing_memo["timestamp"] == memo_data["timestamp"]):
            print("메모가 중복되었습니다. 저장이 취소됩니다.")
            return

    memos_list.append(memo_data)
    with open(memo_file_path, "w", encoding="utf-8") as f:
        json.dump(memos_list, f, ensure_ascii=False, indent=4)

def save_and_reset():
    if st.session_state.new_memo_text.strip():
        save_memo_with_reset(
            memo_file_path,
            st.session_state.new_memo_text.strip(),
            author=st.session_state.author_name
        )
        st.session_state.new_memo_text = ""
        st.toast("메모가 저장되었습니다!", icon="✅")
    else:
        st.toast("빈 메모는 저장할 수 없습니다!", icon="⚠️")

st.sidebar.text_input(
    "작성자 이름",
    placeholder="작성자 이름을 입력하세요...",
    key="author_name"
)
st.sidebar.text_area(
    "메모 내용",
    placeholder="여기에 메모를 입력하세요...",
    key="new_memo_text"
)
st.sidebar.button("메모 저장", on_click=save_and_reset)

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

st.sidebar.title("관리자 로그인 🔒")
password = st.sidebar.text_input("비밀번호 입력 🔑", type="password")

if "schedules_upload_confirmed" not in st.session_state:
    st.session_state.schedules_upload_confirmed = False
if "schedules_upload_canceled" not in st.session_state:
    st.session_state.schedules_upload_canceled = False

if "model_example_upload_confirmed" not in st.session_state:
    st.session_state.model_example_upload_confirmed = False
if "model_example_upload_canceled" not in st.session_state:
    st.session_state.model_example_upload_canceled = False

if password:
    correct_password = st.secrets["teams"].get(selected_team)
    if password == correct_password:
        st.session_state.admin_authenticated = True
        st.sidebar.success(f"{selected_team} 관리자 모드 활성화 ✨")

        uploaded_schedule_file = st.sidebar.file_uploader(
            f"{selected_team} 근무표 파일 업로드 🔼",
            type=["xlsx", "csv"],
            key="schedule_uploader"
        )
        if uploaded_schedule_file:
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.button("⭕ 확 인 ⭕", key="confirm_schedule"):
                    st.session_state.schedules_upload_confirmed = True
                    st.session_state.schedules_upload_canceled = False
            with col2:
                if st.button("❌ 취 소 ❌", key="cancel_schedule"):
                    st.session_state.schedules_upload_canceled = True
                    st.session_state.schedules_upload_confirmed = False

            if st.session_state.schedules_upload_confirmed:
                try:
                    if uploaded_schedule_file.name.endswith(".xlsx"):
                        df = pd.read_excel(uploaded_schedule_file, sheet_name=0)
                    elif uploaded_schedule_file.name.endswith(".csv"):
                        uploaded_schedule_file.seek(0)
                        try:
                            df = pd.read_csv(uploaded_schedule_file, encoding='utf-8-sig')
                        except:
                            try:
                                uploaded_schedule_file.seek(0)
                                df = pd.read_csv(uploaded_schedule_file, encoding='utf-8')
                            except:
                                uploaded_schedule_file.seek(0)
                                df = pd.read_csv(uploaded_schedule_file, encoding='cp949')

                    file_path = os.path.join(schedules_folder_path, f"{current_year}_{st.session_state['selected_month']}_{selected_team}_schedule.csv")
                    try:
                        df.to_csv(file_path, index=False, encoding='utf-8-sig')
                        git_auto_commit(file_path, selected_team)
                        st.sidebar.success(f"{st.session_state['selected_month']} 근무표 업로드 완료 ⭕")
                    except Exception as save_error:
                        st.sidebar.error(f"파일 처리 중 오류: {save_error}")
                        git_pull_changes()

                except Exception as e:
                    st.sidebar.error(f"파일 처리 중 오류 발생: {e}")

            elif st.session_state.schedules_upload_canceled:
                file_path = os.path.join(schedules_folder_path, f"{current_year}_{st.session_state['selected_month']}_{selected_team}_schedule.csv")
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        git_auto_commit("*.csv", "File Deletion")
                        st.sidebar.warning(f"{selected_team} 근무표 취소 완료 ❌")
                    except Exception as delete_error:
                        st.sidebar.error(f"삭제 오류: {delete_error}")
                        git_pull_changes()
                else:
                    st.sidebar.warning("삭제할 파일이 존재하지 않습니다.")

        uploaded_model_example_file = st.sidebar.file_uploader(
            f"{selected_team} 범례 파일 업로드 🔼",
            type=["xlsx", "csv"],
            key="model_example_uploader"
        )
        if uploaded_model_example_file:
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.button("⭕ 확 인 ⭕", key="confirm_model_example"):
                    st.session_state.model_example_upload_confirmed = True
                    st.session_state.model_example_upload_canceled = False
            with col2:
                if st.button("❌ 취 소 ❌", key="cancel_model_example"):
                    st.session_state.model_example_upload_canceled = True
                    st.session_state.model_example_upload_confirmed = False

            if st.session_state.model_example_upload_confirmed:
                try:
                    if uploaded_model_example_file.name.endswith(".xlsx"):
                        df = pd.read_excel(uploaded_model_example_file, sheet_name=0)
                    elif uploaded_model_example_file.name.endswith(".csv"):
                        uploaded_model_example_file.seek(0)
                        try:
                            df = pd.read_csv(uploaded_model_example_file, encoding='utf-8-sig')
                        except:
                            try:
                                uploaded_model_example_file.seek(0)
                                df = pd.read_csv(uploaded_model_example_file, encoding='utf-8')
                            except:
                                uploaded_model_example_file.seek(0)
                                df = pd.read_csv(uploaded_model_example_file, encoding='cp949')

                    file_path = os.path.join(model_example_folder_path, f"{selected_team}_model_example.csv")
                    try:
                        df.to_csv(file_path, index=False, encoding='utf-8-sig')
                        git_auto_commit(file_path, selected_team)
                        st.sidebar.success(f"{selected_team} 범례 업로드 완료 ⭕")
                    except Exception as save_error:
                        st.sidebar.error(f"파일 처리 중 오류 발생: {save_error}")
                        git_pull_changes()

                except Exception as e:
                    st.sidebar.error(f"파일 처리 중 오류 발생: {e}")

            elif st.session_state.model_example_upload_canceled:
                file_path = os.path.join(model_example_folder_path, f"{selected_team}_model_example.csv")
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        git_auto_commit("*.csv", "File Deletion")
                        st.sidebar.warning(f"{selected_team} 범례 취소 완료 ❌")
                    except Exception as delete_error:
                        st.sidebar.error(f"파일 삭제 중 오류 발생: {delete_error}")
                        git_pull_changes()
                else:
                    st.sidebar.warning("삭제할 파일이 존재하지 않습니다.")
    else:
        st.sidebar.error("❌ 비밀번호 오류 ❌")

st.sidebar.markdown("🙋:blue[문의 : 관제SO팀]")

try:
    df = pd.read_csv(schedules_file_path)
    if st.session_state["selected_date"].month == current_month:
        default_date = today_date
    else:
        default_date = datetime(current_year, selected_month_num, 1)

    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.header(f"{selected_team} {st.session_state['selected_month']} 근무표")
    with col2:
        buffer = BytesIO()
        df.to_csv(buffer, index=False, encoding="utf-8-sig")
        buffer.seek(0)
        st.write("")
        st.download_button(
            label="📊 엑셀 다운로드",
            data=buffer,
            file_name=f"{selected_team}_{st.session_state['selected_month']}_근무표.csv",
            mime="text/csv"
        )

    try:
        df_schedule = pd.read_csv(schedules_file_path)
        df_model = pd.read_csv(model_example_file_path)
        df_model = df_model.dropna(subset=["실제 근무", "팀 근무기호"])
        work_mapping = dict(zip(df_model["팀 근무기호"], df_model["실제 근무"]))

        # 날짜 선택
        st.subheader("날짜 선택 📅")
        selected_date = st.date_input(
            "날짜를 선택하세요:",
            key="selected_date",
            on_change=update_month_from_date
        )
        today_column = f"{selected_date.day}({['월','화','수','목','금','토','일'][selected_date.weekday()]})"
        df_schedule.columns = df_schedule.columns.str.strip()

        if today_column in df_schedule.columns:
            df_schedule["근무 형태"] = df_schedule[today_column].map(work_mapping).fillna("")
            excluded_keywords = ["휴", "숙", "대휴(주)", "휴대(주)"]
            filtered_schedule = df_schedule[~df_schedule[today_column].isin(excluded_keywords)].copy()
            day_shift = filtered_schedule[filtered_schedule["근무 형태"].str.contains("주", na=False)].copy()
            night_shift = filtered_schedule[filtered_schedule["근무 형태"].str.contains("야", na=False)].copy()

            day_shift["우선순위"] = day_shift["파트 구분"].apply(lambda x: 0 if "총괄" in x else 1)
            night_shift["우선순위"] = night_shift["파트 구분"].apply(lambda x: 0 if "총괄" in x else 1)

            day_shift.sort_values(by=["우선순위", "파트 구분", "이름"], ascending=[True, True, True], inplace=True)
            night_shift.sort_values(by=["우선순위", "파트 구분", "이름"], ascending=[True, True, True], inplace=True)

            st.subheader(f"{selected_date.strftime('%Y-%m-%d')} {selected_team} 근무자 📋")

            col1, col2 = st.columns(2)
            with col1:
                st.write("주간 근무자 ☀️")
                if not day_shift.empty:
                    for part in day_shift["파트 구분"].unique():
                        part_group = day_shift[day_shift["파트 구분"] == part]
                        part_display_day = part_group[["파트 구분", "이름", today_column]].rename(
                            columns={"파트 구분": "파트", today_column: "근무"})
                        part_display_day["파트"] = part_display_day["파트"].replace("총괄", "팀장")
                        part_display_day.index = ['🌇'] * len(part_display_day)
                        styled_table_day = part_display_day.style.set_table_styles([
                            {'selector': 'td', 'props': [('text-align', 'center'), ('width', '100px'),
                                                         ('min-width', '100px'), ('max-width', '100px'),
                                                         ('box-sizing', 'border-box')]}
                        ])
                        st.table(styled_table_day)
                else:
                    st.write("주간 근무자가 없습니다.")

            with col2:
                st.write("야간 근무자 🌙")
                if not night_shift.empty:
                    for part in night_shift["파트 구분"].unique():
                        part_group = night_shift[night_shift["파트 구분"] == part]
                        part_display_night = part_group[["파트 구분", "이름", today_column]].rename(
                            columns={"파트 구분": "파트", today_column: "근무"})
                        part_display_night["파트"] = part_display_night["파트"].replace("총괄", "팀장")
                        part_display_night.index = ['🌃'] * len(part_display_night)
                        styled_table_night = part_display_night.style.set_table_styles([
                            {'selector': 'td', 'props': [('text-align', 'center'), ('width', '100px'),
                                                         ('min-width', '100px'), ('max-width', '100px'),
                                                         ('box-sizing', 'border-box')]}
                        ])
                        st.table(styled_table_night)
                else:
                    st.write("야간 근무자가 없습니다.")

                st.write("휴가 근무자 🌴")
                vacation_keywords = ["휴가(주)", "대휴(주)", "대휴", "경조", "연차", "야/연차","숙/연차"]
                vacation_shift = df_schedule[df_schedule[today_column].isin(vacation_keywords)].copy()
                if not vacation_shift.empty:
                    vacation_display = vacation_shift[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"})
                    vacation_display["파트"] = vacation_display["파트"].replace("총괄", "팀장")
                    vacation_display.index = ['🌄'] * len(vacation_display)
                    styled_table_vacation = vacation_display.style.set_table_styles([
                        {'selector': 'td', 'props': [('text-align', 'center'), ('width', '100px'),
                                                     ('min-width', '100px'), ('max-width', '100px'),
                                                     ('box-sizing', 'border-box')]}
                    ])
                    st.table(styled_table_vacation)
                else:
                    st.write("휴가 근무자가 없습니다.")
        else:
            st.warning(f"선택한 날짜 ({today_column})에 해당하는 데이터가 없습니다.")

        def save_monthly_schedules_to_json(date_list, today_team_folder_path, df_schedule, work_mapping):
            for date in date_list:
                month_folder = os.path.join(today_team_folder_path, date.strftime('%Y-%m'))
                if not os.path.exists(month_folder):
                    os.mkdir(month_folder)
                json_file_path = os.path.join(month_folder, f"{date.strftime('%Y-%m-%d')}_schedule.json")
                today_column = f"{date.day}({['월','화','수','목','금','토','일'][date.weekday()]})"
                if today_column in df_schedule.columns:
                    df_schedule["근무 형태"] = df_schedule[today_column].map(work_mapping).fillna("")
                    day_shift = df_schedule[df_schedule["근무 형태"].str.contains("주", na=False)].copy()
                    day_shift_data = day_shift[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"}).to_dict(orient="records")

                    night_shift = df_schedule[df_schedule["근무 형태"].str.contains("야", na=False)].copy()
                    night_shift_data = night_shift[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"}).to_dict(orient="records")

                    vacation_keywords = ["휴가(주)", "대휴(주)", "대휴", "경조", "연차", "야/연차", "숙/연차"]
                    vacation_shift = df_schedule[df_schedule[today_column].isin(vacation_keywords)].copy()
                    vacation_shift_data = vacation_shift[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"}).to_dict(orient="records")

                    schedule_data = {
                        "date": date.strftime('%Y-%m-%d'),
                        "day_shift": day_shift_data,
                        "night_shift": night_shift_data,
                        "vacation_shift": vacation_shift_data
                    }
                else:
                    schedule_data = {
                        "date": date.strftime('%Y-%m-%d'),
                        "day_shift": [],
                        "night_shift": [],
                        "vacation_shift": []
                    }
                with open(json_file_path, "w", encoding="utf-8") as json_file:
                    json.dump(schedule_data, json_file, ensure_ascii=False, indent=4)

        save_monthly_schedules_to_json(date_list, today_team_folder_path, df_schedule, work_mapping)

        # -------------------------------------------------------------------------------
        # API 관련 함수 및 헬퍼 함수
        # -------------------------------------------------------------------------------
        def get_json_file_path(date_str, team):
            today_team_path = os.path.join(today_schedules_root_dir, team)
            month_folder = os.path.join(today_team_path, date_str[:7])
            json_file_path = os.path.join(month_folder, f"{date_str}_schedule.json")
            return json_file_path

        def load_json_data(file_path):
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None

        def validate_date_format(date_str):
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                return True
            except ValueError:
                return False

        def api_handler():
            query_params = st.query_params
            team_list = query_params.get_all("team")
            date_list = query_params.get_all("date")
            if not team_list or not date_list:
                st.write({"status": "error", "message": "team 과 date 파라미터가 필요합니다."})
                return

            selected_team_api = team_list[0]
            selected_date_api = date_list[0]

            # 날짜 형식 검사
            try:
                datetime.strptime(selected_date_api, "%Y-%m-%d")
            except ValueError:
                st.write({"status": "error", "message": "날짜 형식은 YYYY-MM-DD 이어야 합니다."})
                return

            json_file_path = get_json_file_path(selected_date_api, selected_team_api)
            schedule_data = load_json_data(json_file_path)
            if schedule_data:
                st.json({"data": schedule_data})
            else:
                st.write({"status": "error", "message": f"{selected_date_api} ({selected_team_api})에 해당하는 데이터를 찾을 수 없습니다."})

        def main_app():
            # 위에 정의된 기본 스트림릿 앱 로직 모두가 main_app()에서 실행됩니다.
            # (이미 위에서 실행한 내용이 있으므로, 중복 실행하지 않도록 별도 분리)
            pass

        # -------------------------------------------------------------------------------
        # __main__ 조건문: 쿼리 파라미터에 따라 API 모드와 일반 앱 모드를 분기
        # -------------------------------------------------------------------------------
        if __name__ == "__main__":
            params = st.query_params
            if "team" in params and "date" in params:
                api_handler()
            else:
                main_app()

    except FileNotFoundError:
        st.error("❌ 범례가 등록 되지 않았습니다.")
    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")

    exclude_columns = ['본부 구분', '팀 구분', '년/월', '근무 구분']
    filtered_df = df.drop(columns=[col for col in exclude_columns if col in df.columns], errors='ignore')

    gb = GridOptionsBuilder.from_dataframe(filtered_df)
    gb.configure_column("파트 구분", pinned="left")
    gb.configure_column("이름", pinned="left")
    gb.configure_default_column(width=10)
    gb.configure_grid_options(domLayout='normal', alwaysShowHorizontalScroll=True, suppressColumnVirtualisation=True)
    grid_options = gb.build()

    st.subheader("전체 근무표 📆")
    AgGrid(
        filtered_df,
        gridOptions=grid_options,
        height=555,
        theme="streamlit"
    )

    st.subheader("🔍 구성원 근무표 검색")
    employee_name = st.text_input(f"{selected_team} 구성원 이름 입력")
    if employee_name:
        filtered_df = df[df["이름"].str.contains(employee_name, na=False)]
        if not filtered_df.empty:
            st.write(f"{employee_name} 님의 근무표")
            st.dataframe(filtered_df, hide_index=True)
        else:
            st.warning(f"'{employee_name}' 님의 데이터가 없습니다.")

except FileNotFoundError:
    st.info(f"❌ {st.session_state['selected_month']} 근무표가 등록되지 않았습니다.")

st.header(f"{selected_team} - {st.session_state['selected_month']} 메모 📓")

def load_memos(memo_file_path):
    if os.path.exists(memo_file_path):
        with open(memo_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def delete_memo_and_refresh(timestamp):
    if os.path.exists(memo_file_path):
        with open(memo_file_path, "r", encoding="utf-8") as f:
            memos_list = json.load(f)

        updated_memos = [memo for memo in memos_list if memo['timestamp'] != timestamp]
        with open(memo_file_path, "w", encoding="utf-8") as f:
            json.dump(updated_memos, f, ensure_ascii=False, indent=4)

        st.toast("메모가 성공적으로 삭제되었습니다!", icon="💣")
        time.sleep(1)
        st.rerun()

memos_list = load_memos(memo_file_path)
if memos_list:
    for idx, memo in enumerate(reversed(memos_list)):
        timestamp_obj = datetime.strptime(memo['timestamp'], '%Y-%m-%d %H:%M:%S')
        formatted_timestamp = timestamp_obj.strftime('%Y-%m-%d %H:%M')

        st.markdown(f"📢 **{memo['author']}**님 ({formatted_timestamp})")
        st.write("🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻")
        memo_content = memo["note"].replace("\n", "  \n")
        st.markdown(memo_content)
        st.write("🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺")

        if st.button(
            f"🙋 삭제는 관리자에게 문의 부탁드립니다!🗑️ ◽작성자 : {memo['author']} ◽작성시간 : ({formatted_timestamp})",
            key=f"delete_{formatted_timestamp}_{idx}",
            disabled=not st.session_state.admin_authenticated
        ):
            delete_memo_and_refresh(memo['timestamp'])
        st.markdown("---")
else:
    st.info(f"{selected_team}의 {st.session_state['selected_month']}에 저장된 메모가 없습니다.")
