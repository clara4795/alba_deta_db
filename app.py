from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import calendar            
import config
from datetime import datetime

app = Flask(__name__)
app.secret_key = config.SECRET_KEY  # 세션 암호화에 필요 (아무거나 입력 가능)

# 1. 데이터베이스 연결 설정 
DB_HOST = "localhost"
DB_PORT = config.DB_PORT
DB_NAME = "alba2025"    
DB_USER = "db2025"    
DB_PASS = config.DB_PASSWORD       

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )
    return conn

# 2. 메인 페이지 (로그인 화면)
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        
        # SFW: DB에서 이메일과 비밀번호가 일치하는 사용자 찾기
        cur.execute("SELECT user_id, name, email FROM \"User\" WHERE email = %s AND password = %s", (email, password))
        user = cur.fetchone()
        
        cur.close()
        conn.close()

        if user:
            # 로그인 성공! 세션에 정보 저장
            session['user_id'] = user[0]
            session['name'] = user[1]
            return redirect(url_for('dashboard')) # 대시보드로 이동
        else:
            flash('이메일 또는 비밀번호가 틀렸습니다.')
            return redirect(url_for('login'))

    return render_template('login.html')

# 3. 로그인 성공 후 이동할 화면 (대시보드)
# app.py의 dashboard 함수 교체

# app.py 의 dashboard 함수를 아래 코드로 통째로 교체하세요.

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # 1. URL에서 년/월 가져오기 (없으면 현재 시스템 날짜 기준)
    # request.args.get('키', 기본값, 타입) 함수를 씁니다.
    now = datetime.now()
    year = request.args.get('year', 2025, type=int)  # 테스트 데이터가 있는 2025년을 기본값으로
    month = request.args.get('month', 12, type=int)
    
    # 2. '이전 달' 계산 로직
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    # 3. '다음 달' 계산 로직
    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    conn = get_db_connection()
    cur = conn.cursor()
    
    # 4. 해당 년/월의 스케줄 조회 (SQL은 그대로!)
    sql = """
        SELECT 
            s.schedule_id, 
            st.name, 
            s.start_time, 
            s.end_time,
            d.status
        FROM Schedule s
        JOIN Store st ON s.store_id = st.store_id
        LEFT JOIN Deta d ON s.schedule_id = d.schedule_id
        WHERE s.user_id = %s 
          AND EXTRACT(YEAR FROM s.start_time) = %s
          AND EXTRACT(MONTH FROM s.start_time) = %s
        ORDER BY s.start_time ASC
    """
    cur.execute(sql, (user_id, year, month))
    rows = cur.fetchall()

    # ★ 추가됨: 내가 '수락'했고 아직 '승인대기' 중인 스케줄 조회
    sql_pending = """
        SELECT d.deta_id, st.name, s.start_time, s.end_time
        FROM Deta d
        JOIN Schedule s ON d.schedule_id = s.schedule_id
        JOIN Store st ON s.store_id = st.store_id
        WHERE d.accepter_id = %s 
          AND d.status = '승인대기'
          AND EXTRACT(YEAR FROM s.start_time) = %s AND EXTRACT(MONTH FROM s.start_time) = %s
    """
    cur.execute(sql_pending, (user_id, year, month))
    pending_rows = cur.fetchall()

    sql_open = """
            SELECT 
                d.deta_id, 
                s.schedule_id,
                st.name, 
                u.name, -- 요청자 이름
                s.start_time, 
                s.end_time
            FROM Deta d
            JOIN Schedule s ON d.schedule_id = s.schedule_id
            JOIN Store st ON s.store_id = st.store_id
            JOIN "User" u ON d.requester_id = u.user_id
            WHERE d.status = '구하는중'
            AND d.requester_id != %s  -- 내가 쓴 글은 제외
            AND s.store_id IN (SELECT store_id FROM StoreUser WHERE user_id = %s) -- 내가 일하는 매장만
        """
    cur.execute(sql_open, (user_id, user_id))
    open_requests = cur.fetchall()
        
    cur.close()
    conn.close()

    schedule_map = {}
    for row in rows:
        day = row[2].day
        deta_status = row[4] if row[4] else '없음'
        info = {
            'type': 'confirmed',
            'id': row[0],
            'store_name': row[1],
            'time_str': f"{row[2].strftime('%H:%M')} ~ {row[3].strftime('%H:%M')}",
            'status': deta_status
        }
        if day in schedule_map:
            schedule_map[day].append(info)
        else:
            schedule_map[day] = [info]

    # B. ★ 추가됨: 승인 대기 스케줄 넣기 (구별을 위해 type='pending' 설정)
    for row in pending_rows:
        day = row[2].day
        info = {
            'type': 'pending', # 승인 대기 중인 스케줄
            'deta_id': row[0], 
            'store_name': row[1],
            'time_str': f"{row[2].strftime('%H:%M')} ~ {row[3].strftime('%H:%M')}",
            'status': '승인대기'
        }
        if day in schedule_map: schedule_map[day].append(info)
        else: schedule_map[day] = [info]

    cal = calendar.monthcalendar(year, month)

    # 5. HTML로 계산된 '이전/다음' 정보를 같이 넘겨줍니다.
    return render_template('dashboard.html', 
                           name=session['name'], 
                           year=year, 
                           month=month, 
                           calendar_matrix=cal, 
                           schedule_map=schedule_map,
                           open_requests=open_requests,
                           prev_year=prev_year, prev_month=prev_month,
                           next_year=next_year, next_month=next_month)

# app.py 의 request_deta 함수를 이걸로 교체하고, 그 밑에 cancel_deta를 추가하세요.

# 1. 대타 요청 함수 (수정됨: 상태를 '대기중' -> '구하는중'으로 변경)
@app.route('/request_deta/<int:schedule_id>', methods=['POST'])
def request_deta(schedule_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 상태를 '구하는중'으로 명시해서 저장
        cur.execute("""
            INSERT INTO Deta (schedule_id, requester_id, status)
            VALUES (%s, %s, '구하는중')
        """, (schedule_id, user_id))
        conn.commit()
        flash('대타 요청을 등록했습니다.')
    except Exception as e:
        conn.rollback()
        flash('오류가 발생했습니다.')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('dashboard'))

# 2. ★ 대타 요청 취소 함수
@app.route('/cancel_deta/<int:schedule_id>', methods=['POST'])
def cancel_deta(schedule_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 내가 요청한 대타이고, 아직 '구하는중' 상태일 때만 삭제 가능 (승인대기 상태면 취소 불가하게)
        cur.execute("""
            DELETE FROM Deta 
            WHERE schedule_id = %s AND requester_id = %s AND status = '구하는중'
        """, (schedule_id, user_id))
        
        if cur.rowcount > 0:
            conn.commit()
            flash('대타 요청을 취소했습니다.')
        else:
            flash('취소할 수 없는 상태이거나 권한이 없습니다.')
            
    except Exception as e:
        conn.rollback()
        flash('오류 발생: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

# 2. ★ 대타 수락 처리 함수 (새로 추가!)
@app.route('/accept_deta/<int:deta_id>/<int:schedule_id>', methods=['POST'])
def accept_deta(deta_id, schedule_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. 스케줄 시간 조회
        cur.execute("SELECT start_time, end_time FROM Schedule WHERE schedule_id = %s", (schedule_id,))
        target_schedule = cur.fetchone()
        target_start = target_schedule[0]
        target_end = target_schedule[1]
        
        # 2. ★ 시간 겹침 확인 (Transaction 조건)
        # 내 스케줄 중에서, 타겟 스케줄과 시간이 겹치는게 있는지 카운트
        check_sql = """
            SELECT COUNT(*) FROM Schedule 
            WHERE user_id = %s 
              AND (
                  (start_time < %s AND end_time > %s) -- 시간이 겹치는 조건
              )
        """
        cur.execute(check_sql, (user_id, target_end, target_start))
        conflict_count = cur.fetchone()[0]
        
        if conflict_count > 0:
            flash('❌ 오류: 해당 시간에 이미 본인의 근무가 있어 수락할 수 없습니다!')
        else:
            # 3. 겹치는 게 없으면 수락 처리 (Update)
            cur.execute("""
                UPDATE Deta 
                SET accepter_id = %s, status = '승인대기' 
                WHERE deta_id = %s AND status = '구하는중'
            """, (user_id, deta_id))
            
            conn.commit()
            flash('✅ 대타 수락 완료! 매니저의 승인을 기다립니다.')
            
    except Exception as e:
        conn.rollback()
        flash('오류 발생: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

# 2. ★ 수락 취소 함수 (새로 추가)
@app.route('/cancel_accept/<int:deta_id>', methods=['POST'])
def cancel_accept(deta_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 내 이름(accepter_id)을 지우고, 상태를 다시 '구하는중'으로 되돌림 (시장에 다시 내놓기)
        cur.execute("""
            UPDATE Deta 
            SET accepter_id = NULL, status = '구하는중' 
            WHERE deta_id = %s AND accepter_id = %s AND status = '승인대기'
        """, (deta_id, user_id))
        
        if cur.rowcount > 0:
            conn.commit()
            flash('수락을 취소했습니다. 해당 스케줄은 다시 대타 목록에 올라갑니다.')
        else:
            flash('취소할 수 없는 상태입니다.')
            
    except Exception as e:
        conn.rollback()
        flash('오류 발생: ' + str(e))
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)