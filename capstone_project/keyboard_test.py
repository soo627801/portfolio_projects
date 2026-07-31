import serial
from pynput.keyboard import Controller, Key
import time

# ① 시리얼 포트 설정 (환경에 맞게 'COM3' 부분 수정)
ser = serial.Serial('/dev/cu.usbmodem11201', 9600, timeout=1)

# ② 키보드 컨트롤러 초기화
keyboard = Controller()

print("foot switch 입력을 감지 중... (Ctrl+C로 종료)")

try:
    while True:
        # ③ 아두이노에서 한 줄 입력 읽기
        line = ser.readline().decode('utf-8').strip()

        if line == "PRESSED":
            print("foot switch 눌림 → F5 키 입력 발생!")

            # ④ 실제 F5 키 누르기
            keyboard.press(Key.f5)
            keyboard.release(Key.f5)

            # 중복 방지 딜레이
            time.sleep(0.3)

except KeyboardInterrupt:
    print("\n프로그램 종료됨.")
finally:
    ser.close()