import os
os.environ["GIT_OPTIONAL_LOCKS"] = "0" #index.lock 파일 관련 오류 해지
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
from git import Repo, GitCommandError
import subprocess

# -------------------------------------------------------------------
# Git 사용자 정보 강제 재설정 함수
# -------------------------------------------------------------------
def reset_git_config():
    subprocess.run(['git', 'config', '--global', 'user.name', st.secrets["GITHUB"]["USER_NAME"]])
    subprocess.run(['git', 'config', '--global', 'user.email', st.secrets["GITHUB"]["USER_EMAIL"]])

reset_git_config()
# -------------------------------------------------------------------
# 기본 설정
# -------------------------------------------------------------------
repo_root = "."  # 저장소 루트 (프로젝트 루트)
korea_tz = pytz.timezone("Asia/Seoul")

# 디렉토리 경로 설정
schedules_root_dir = "team_schedules"
model_example_root_dir = "team_model_example"
today_schedules_root_dir = "team_today_schedules"
memo_root_dir = "team_memo"

# -------------------------------------------------------------------
# 디렉토리 생성 함수: 파일 경로가 없으면 생성
# -------------------------------------------------------------------
def create_dir_safe(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        # 빈 폴더도 Git에 반영되도록 .gitkeep 파일 생성
        gitkeep_path = os.path.join(path, ".gitkeep")
        with open(gitkeep_path, "w") as f:
            f.write("")

for folder in [schedules_root_dir, model_example_root_dir, today_schedules_root_dir, memo_root_dir]:
    create_dir_safe(folder)

# -------------------------------------------------------------------
# Personal Access Token(PAT)가 포함된 인증 URL 생성 함수
# -------------------------------------------------------------------
def build_auth_repo_url():
    """
    st.secrets에 등록된 REPO_URL과 TOKEN을 이용하여,
    토큰이 포함된 인증 URL을 생성합니다.
    예: "https://github.com/devkylo/RSW.git" → "https://<TOKEN>:x-oauth-basic@github.com/devkylo/RSW.git"
    """
    repo_url = st.secrets["GITHUB"]["REPO_URL"]
    token = st.secrets["GITHUB"]["TOKEN"]
    if token:
        auth_repo_url = repo_url.replace("https://", f"https://{token}:x-oauth-basic@")
    else:
        auth_repo_url = repo_url
    return auth_repo_url

# -------------------------------------------------------------------
# 1) Git 저장소 초기화 및 원격 연결 (GitPython, PAT 적용)
# -------------------------------------------------------------------
def git_init_repo():
    """Git 저장소 초기화 및 원격 연결 (PAT 적용)"""
    # 필수 폴더들 생성 (team_schedules, model_example 등)
    for folder in [schedules_root_dir, model_example_root_dir, today_schedules_root_dir, memo_root_dir]:
        create_dir_safe(folder)
    
    # repo_root 경로에 .git 폴더가 없으면 저장소 초기화
    if not os.path.exists(os.path.join(repo_root, ".git")):
        repo = Repo.init(repo_root, initial_branch="main")
        auth_repo_url = build_auth_repo_url()
        repo.create_remote('origin', auth_repo_url)
        
        with repo.config_writer() as config:
            config.set_value("user", "name", st.secrets["GITHUB"]["USER_NAME"])
            config.set_value("user", "email", st.secrets["GITHUB"]["USER_EMAIL"])
        
        # .gitignore 생성 - Git에 포함하지 않을 폴더만 지정 (team_schedules는 커밋)
        gitignore_path = os.path.join(repo_root, ".gitignore")
        with open(gitignore_path, "w") as f:
            f.write("team_today_schedules/\nteam_memo/\n*.tmp\n")
        
        repo.index.add([gitignore_path])
        repo.index.commit("Initial commit with .gitignore")
        repo.git.branch("-M", "main")
        
        #st.toast("Git 저장소가 초기화되었습니다.", icon="✅")

# -------------------------------------------------------------------
# 2) 변경사항 자동 커밋 및 푸시 함수 (push 전 원격 URL 재설정 포함)
# -------------------------------------------------------------------
def git_auto_commit(file_path, team_name):
    """
    파일 저장 후 자동 커밋 및 원격 푸시 (파일이 존재하면 add, 없으면 remove하여 삭제를 반영)
    """
    commit_message = f"Auto-commit: {team_name} {datetime.now(korea_tz).strftime('%Y-%m-%d %H:%M')}"
    try:
        repo = Repo(repo_root)  # repo_root 기준으로 작업
        # file_path를 repo_root 기준 상대경로로 변환
        relative_path = os.path.relpath(file_path, repo_root)
        # 파일이 존재하면 추가, 존재하지 않으면 삭제 상태를 인덱스에 반영
        if os.path.exists(file_path):
            repo.index.add([relative_path])
        else:
            repo.index.remove([relative_path])
        repo.index.commit(commit_message)
        repo.git.branch("-M", "main")
        origin = repo.remote(name='origin')
        # 최신 PAT가 포함된 URL로 재설정 후 push
        origin.set_url(build_auth_repo_url())
        origin.push("HEAD:refs/heads/main")
    except GitCommandError as e:
        st.error(f"Git 작업 오류: {e}")


# -------------------------------------------------------------------
# 3) 원격 저장소의 최신 변경사항 동기화 (pull)
# -------------------------------------------------------------------
def git_pull_changes():
    """원격 저장소의 최신 변경사항 동기화 (main 브랜치)
    
    동기화 도중 st.session_state.cancel_sync 플래그가 True인 경우 동기화를 중단합니다.
    """
    st.session_state.sync_active = True
    st.session_state.cancel_sync = False  # 동기화 시작 시 취소 플래그 초기화
    try:
        process = subprocess.Popen(
            ["git", "pull", "origin", "main"],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # 동기화 진행 중 주기적으로 취소 여부 확인
        while process.poll() is None:
            if st.session_state.get("cancel_sync", False):
                process.kill()
                st.toast("동기화가 중단되었습니다.", icon="⛔")
                return
            time.sleep(0.1)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            st.error(f"Git 동기화 오류: {stderr.decode()}")
        else:
            st.toast("GitHub 최신 데이터 동기화 완료!", icon="🔄")
    except Exception as e:
        st.error(f"동기화 중 오류 발생: {e}")
    finally:
        st.session_state.sync_active = False


# -------------------------------------------------------------------
# Git 초기화 및 동기화 (한번만 실행: 세션 상태 사용)
# -------------------------------------------------------------------
if 'git_initialized' not in st.session_state:
    git_init_repo()
    git_pull_changes()
    st.session_state.git_initialized = True

# -------------------------------------------------------------------
# Streamlit UI - 팀, 월, 메모, 파일 업로드 등
# -------------------------------------------------------------------
st.title("Rotation Scheduler WebService 💻")

# 팀 및 월 선택
st.sidebar.title("팀 선택 ✅")
teams = ["관제SO팀", "동부SO팀", "보라매SO팀", "백본SO팀", "보안SO팀", "성수SO팀", "중부SO팀"]
selected_team = st.sidebar.radio("", teams)

today_date = datetime.now(korea_tz)
current_year = today_date.year
current_month = today_date.month

st.sidebar.title("월 선택 📅")
months = [f"{i}월" for i in range(1, 13)]
current_month_index = current_month - 1
selected_month = st.sidebar.selectbox("", months, index=current_month_index)
selected_month_num = int(selected_month.replace("월", ""))

# 팀별 폴더 경로 설정
schedules_folder_path = os.path.join(schedules_root_dir, selected_team)
model_example_folder_path = os.path.join(model_example_root_dir, selected_team)
today_team_folder_path = os.path.join(today_schedules_root_dir, selected_team)
memo_team_folder_path = os.path.join(memo_root_dir, selected_team)

for folder in [schedules_folder_path, model_example_folder_path, today_team_folder_path, memo_team_folder_path]:
    create_dir_safe(folder)

# 날짜 관련 변수 (근무표 생성을 위해)
start_date = datetime(current_year, selected_month_num, 1)
end_date = (start_date + timedelta(days=31)).replace(day=1) - timedelta(days=1)
date_list = [(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)]

# 파일 경로 설정
schedules_file_path = os.path.join(schedules_folder_path, f"{current_year}_{selected_month}_{selected_team}_schedule.csv")
model_example_file_path = os.path.join(model_example_folder_path, f"{selected_team}_model_example.csv")
memo_file_path = os.path.join(memo_team_folder_path, f"{current_year}_{selected_month}_memos.json")

# -------------------------------------------------------------------
# 메모 관련 함수 및 UI
# -------------------------------------------------------------------
st.sidebar.title("메모 추가 ✏️")

if 'new_memo_text' not in st.session_state:
    st.session_state.new_memo_text = ""
if 'author_name' not in st.session_state:
    st.session_state.author_name = ""

def get_korea_time():
    return datetime.now(korea_tz).strftime('%Y-%m-%d %H:%M:%S')

def save_memo_with_reset(memo_file_path, memo_text, author=""):
    try:
        # 메모 폴더 생성
        memo_dir = os.path.dirname(memo_file_path)
        create_dir_safe(memo_dir)
        
        memo_data = {
            "note": memo_text,
            "author": author, 
            "timestamp": get_korea_time()
        }
        
        # 파일이 있으면 내용 확인 후 JSON 로드, 없거나 비어있다면 빈 리스트로 시작
        if os.path.exists(memo_file_path):
            with open(memo_file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    memos_list = []
                else:
                    memos_list = json.loads(content)
        else:
            memos_list = []
            
        # 중복 체크
        for existing_memo in memos_list:
            if (existing_memo["note"] == memo_data["note"] and
                existing_memo["author"] == memo_data["author"] and 
                existing_memo["timestamp"] == memo_data["timestamp"]):
                st.info("메모가 중복되었습니다. 저장이 취소됩니다.")
                return False
                
        # 메모 추가 및 저장
        memos_list.append(memo_data)
        with open(memo_file_path, "w", encoding="utf-8") as f:
            json.dump(memos_list, f, ensure_ascii=False, indent=4)
            
        return True
            
    except Exception as e:
        st.error(f"메모 저장 중 오류 발생: {e}")
        return False

def save_and_reset():
    if st.session_state.new_memo_text.strip():
        # 만약 동기화 중이면 취소 플래그 설정
        if st.session_state.get("sync_active", False):
            st.session_state.cancel_sync = True
            time.sleep(0.2)  # 동기화 종료를 위해 잠시 대기

        # GitHub 최신 데이터 동기화
        git_pull_changes()
        
        # 메모 저장 시도
        if save_memo_with_reset(memo_file_path,
                              st.session_state.new_memo_text.strip(),
                              author=st.session_state.author_name):
                              
            try:
                # Git에 변경사항 커밋 및 푸시
                git_auto_commit(memo_file_path, selected_team)
                st.session_state.new_memo_text = ""
                st.toast("메모가 저장되었습니다!", icon="✅")
            except Exception as e:
                st.error(f"Git 저장 중 오류 발생: {e}")
    else:
        st.toast("빈 메모는 저장할 수 없습니다!", icon="⚠️")


# -------------------------------------------------------------------
# 관리자 로그인 및 파일 업로드
# -------------------------------------------------------------------
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

st.sidebar.title("관리자 로그인 🔒")
password = st.sidebar.text_input("비밀번호 입력 🔑", type="password")

# 업로드 처리 상태 변수 초기화
if "schedules_upload_confirmed" not in st.session_state:
    st.session_state.schedules_upload_confirmed = False
if "schedules_upload_canceled" not in st.session_state:
    st.session_state.schedules_upload_canceled = False
if "model_example_upload_confirmed" not in st.session_state:
    st.session_state.model_example_upload_confirmed = False
if "model_example_upload_canceled" not in st.session_state:
    st.session_state.model_example_upload_canceled = False

if password:
    # st.secrets의 teams 섹션에 등록된 비밀번호 사용
    correct_password = st.secrets["teams"].get(selected_team)
    if password == correct_password:
        st.session_state.admin_authenticated = True
        st.sidebar.success(f"{selected_team} 관리자 모드 활성화 ✨")

        # 근무표 파일 업로드
        uploaded_schedule_file = st.sidebar.file_uploader(
            f"{selected_team} 근무표 파일 업로드 🔼",
            type=["xlsx", "csv"],
            key="schedule_uploader"
        )
        if uploaded_schedule_file:
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.button("⭕ 확 인 ⭕", key="confirm_schedule"):
                    # 동기화 진행 중이면 취소 플래그 설정 후 잠시 대기
                    if st.session_state.get("sync_active", False):
                        st.session_state.cancel_sync = True
                        time.sleep(0.2)
                    st.session_state.schedules_upload_confirmed = True
                    st.session_state.schedules_upload_canceled = False
            with col2:
                if st.button("❌ 취 소 ❌", key="cancel_schedule"):
                    # 동기화 진행 중이면 취소 플래그 설정 후 잠시 대기
                    if st.session_state.get("sync_active", False):
                        st.session_state.cancel_sync = True
                        time.sleep(0.2)
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
                        except Exception:
                            try:
                                uploaded_schedule_file.seek(0)
                                df = pd.read_csv(uploaded_schedule_file, encoding='utf-8')
                            except Exception:
                                uploaded_schedule_file.seek(0)
                                df = pd.read_csv(uploaded_schedule_file, encoding='cp949')

                    # 파일 저장 및 Git 커밋/푸시
                    df.to_csv(schedules_file_path, index=False, encoding='utf-8-sig')
                    git_auto_commit(schedules_file_path, selected_team)
                    st.sidebar.success(f"{selected_month} 근무표 업로드 완료 ⭕")
                except Exception as e:
                    st.sidebar.error(f"파일 처리 중 오류 발생: {e}")
                    git_pull_changes()
            elif st.session_state.schedules_upload_canceled:
                file_path = os.path.join(schedules_file_path, f"{current_year}_{selected_month}_{selected_team}_schedule.csv")
                try:
                    # 파일이 있으면 삭제; 없으면 그냥 넘어감
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    # 파일이 없어도 git_auto_commit()을 호출하여 삭제 상태를 Git에 반영
                    git_auto_commit(file_path, selected_team)
                    st.sidebar.warning(f"{selected_team} 범례 취소 완료 ❌")
                except Exception as delete_error:
                    st.sidebar.error(f"파일 삭제 중 오류 발생: {delete_error}")
                    git_pull_changes()
                else:
                    st.sidebar.warning("삭제할 파일이 존재하지 않습니다.")

        # 범례 파일 업로드
        uploaded_model_example_file = st.sidebar.file_uploader(
            f"{selected_team} 범례 파일 업로드 🔼",
            type=["xlsx", "csv"],
            key="model_example_uploader"
        )
        if uploaded_model_example_file:
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.button("⭕ 확 인 ⭕", key="confirm_model_example"):
                    # 동기화 진행 중이면 취소 플래그 설정 후 잠시 대기
                    if st.session_state.get("sync_active", False):
                        st.session_state.cancel_sync = True
                        time.sleep(0.2)
                    st.session_state.model_example_upload_confirmed = True
                    st.session_state.model_example_upload_canceled = False
            with col2:
                if st.button("❌ 취 소 ❌", key="cancel_model_example"):
                    # 동기화 진행 중이면 취소 플래그 설정 후 잠시 대기
                    if st.session_state.get("sync_active", False):
                        st.session_state.cancel_sync = True
                        time.sleep(0.2)
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
                        except Exception:
                            try:
                                uploaded_model_example_file.seek(0)
                                df = pd.read_csv(uploaded_model_example_file, encoding='utf-8')
                            except Exception:
                                uploaded_model_example_file.seek(0)
                                df = pd.read_csv(uploaded_model_example_file, encoding='cp949')
                    file_path = os.path.join(model_example_folder_path, f"{selected_team}_model_example.csv")
                    df.to_csv(file_path, index=False, encoding='utf-8-sig')
                    git_auto_commit(file_path, selected_team)
                    st.sidebar.success(f"{selected_team} 범례 업로드 완료 ⭕")
                except Exception as e:
                    st.sidebar.error(f"파일 처리 중 오류 발생: {e}")
                    git_pull_changes()
            elif st.session_state.model_example_upload_canceled:
                file_path = os.path.join(model_example_folder_path, f"{selected_team}_model_example.csv")
                try:
                    # 파일이 있으면 삭제; 없으면 그냥 넘어감
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    # 파일이 없어도 git_auto_commit()을 호출하여 삭제 상태를 Git에 반영
                    git_auto_commit(file_path, selected_team)
                    st.sidebar.warning(f"{selected_team} 범례 취소 완료 ❌")
                except Exception as delete_error:
                    st.sidebar.error(f"파일 삭제 중 오류 발생: {delete_error}")
                    git_pull_changes()
                else:
                    st.sidebar.warning("삭제할 파일이 존재하지 않습니다.")
    else:
        st.sidebar.error("❌ 비밀번호 오류 ❌")

st.sidebar.markdown("🙋 :blue[문의 : 관제SO팀]")

try:
    df = pd.read_csv(schedules_file_path)
    if selected_month_num == current_month:
        default_date = today_date
    else:
        default_date = datetime(current_year, selected_month_num, 1)

    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.header(f"{selected_team} {selected_month} 근무표")
    with col2:
        buffer = BytesIO()
        df.to_csv(buffer, index=False, encoding="utf-8-sig")
        buffer.seek(0)
        st.write("")
        st.download_button(
            label="📊 엑셀 다운로드",
            data=buffer,
            file_name=f"{selected_team}_{selected_month}_근무표.csv",
            mime="text/csv"
        )

    try:
        df_schedule = pd.read_csv(schedules_file_path)
        df_model = pd.read_csv(model_example_file_path)
        df_model = df_model.dropna(subset=["실제 근무", "팀 근무기호"])
        work_mapping = dict(zip(df_model["팀 근무기호"], df_model["실제 근무"]))

        if selected_month_num == current_month:
            default_date = today_date.date()
        else:
            default_date = datetime(current_year, selected_month_num, 1).date()

        st.subheader("날짜 선택 📅")
        selected_date = st.date_input("날짜를 선택하세요:", default_date)
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
            created_files = []  # 생성된 JSON 파일 경로를 저장하는 리스트
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
                        columns={"파트 구분": "파트", today_column: "근무"}
                    ).to_dict(orient="records")

                    night_shift = df_schedule[df_schedule["근무 형태"].str.contains("야", na=False)].copy()
                    night_shift_data = night_shift[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"}
                    ).to_dict(orient="records")

                    vacation_keywords = ["휴가(주)", "대휴(주)", "대휴", "경조", "연차", "야/연차", "숙/연차"]
                    vacation_shift = df_schedule[df_schedule[today_column].isin(vacation_keywords)].copy()
                    vacation_shift_data = vacation_shift[["파트 구분", "이름", today_column]].rename(
                        columns={"파트 구분": "파트", today_column: "근무"}
                    ).to_dict(orient="records")

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
                created_files.append(json_file_path)
            
            # GitHub와 동기화: 원격 변경사항을 pull한 후 생성된 파일들을 개별 커밋 및 푸시
            git_pull_changes()
            for file_path in created_files:
                git_auto_commit(file_path, selected_team)

        # 함수 실행 예시
        save_monthly_schedules_to_json(date_list, today_team_folder_path, df_schedule, work_mapping)


        def validate_date_format(date_str):
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                return True
            except ValueError:
                return False

        def get_json_file_path(date_str, team):
            today_team_path = os.path.join("team_today_schedules", team)
            month_folder = os.path.join(today_team_path, date_str[:7])
            json_file_path = os.path.join(month_folder, f"{date_str}_schedule.json")
            return json_file_path

        def load_json_data(file_path):
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None

        def api_handler():
            query_params = st.query_params
            team_values = query_params.get("team")
            date_values = query_params.get("date")
            if not team_values or not date_values:
                st.write({"status": "error", "message": "team 과 date 파라미터가 필요합니다."})
                return

            # URL 인코딩된 값 복원
            selected_team = unquote(team_values)
            selected_date = unquote(date_values)
            
            # 날짜 형식 검사
            try:
                datetime.strptime(selected_date, "%Y-%m-%d")
            except ValueError:
                st.write({"status": "error", "message": "날짜 형식은 YYYY-MM-DD 이어야 합니다."})
                return

            json_file_path = get_json_file_path(selected_date, selected_team)
            schedule_data = load_json_data(json_file_path)
            if schedule_data:
                json_str = json.dumps({"data": schedule_data}, ensure_ascii=False, indent=2)
                st.markdown(f"<pre>{json_str}</pre>", unsafe_allow_html=True)
            else:
                st.write({"status": "error", "message": f"{selected_date} ({selected_team})에 해당하는 데이터를 찾을 수 없습니다."})

        def main_app():
            pass

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
            st.write(f"**{employee_name}** 님의 근무표")
            st.dataframe(filtered_df, hide_index=True)
        else:
            st.warning(f"'{employee_name}' 님의 데이터가 없습니다.")

except FileNotFoundError:
    st.info(f"❌ {selected_month} 근무표가 등록되지 않았습니다.")

st.header(f"{selected_team} - {selected_month} 메모 📓")

def load_memos(memo_file_path):
    if os.path.exists(memo_file_path):
        with open(memo_file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:  # 파일이 빈 경우
                return []
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                st.error(f"JSON 파일 읽기 오류: {e}")
                return []
    return []


def delete_memo_and_refresh(timestamp):
    # 관리자 인증 체크: 관리자 로그인 상태가 아니라면 삭제 진행하지 않음.
    if not st.session_state.get("admin_authenticated", False):
        return

    # 만약 동기화 중이면 취소 플래그 설정 (다른 동작이 시작되면 동기화를 중단)
    if st.session_state.get("sync_active", False):
        st.session_state.cancel_sync = True
        time.sleep(0.2)  # 동기화 종료를 위해 잠시 대기

    # 최신 GitHub 데이터를 반영
    git_pull_changes()

    if os.path.exists(memo_file_path):
        with open(memo_file_path, "r", encoding="utf-8") as f:
            memos_list = json.load(f)

        updated_memos = [memo for memo in memos_list if memo['timestamp'] != timestamp]

        if updated_memos:
            with open(memo_file_path, "w", encoding="utf-8") as f:
                json.dump(updated_memos, f, ensure_ascii=False, indent=4)
        else:
            os.remove(memo_file_path)
    
    git_auto_commit(memo_file_path, selected_team)

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
        
        # 관리자 로그인 상태일 경우에만 삭제 버튼 활성화
        if st.session_state.get("admin_authenticated", False):
            if st.button(
                f"❌ 메모 삭제 ❌ (작성자: {memo['author']} / 작성 시간: {formatted_timestamp})",
                key=f"delete_{formatted_timestamp}_{idx}"
            ):
                delete_memo_and_refresh(memo['timestamp'])
        else:
            st.info("🙋 삭제는 관리자에게 문의 부탁드립니다!🗑️")
        
        st.markdown("---")
else:
    st.info(f"{selected_team}의 {selected_month}에 저장된 메모가 없습니다.")
