import sys
import cv2
import numpy as np
import tensorflow as tf
import mediapipe as mp
import serial
import threading
import time
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLabel, QMessageBox


class FootSwitchHandler(QObject):
    """발키보드 신호를 처리하는 클래스"""
    foot_switch_pressed = pyqtSignal()

    def __init__(self, serial_port='/dev/cu.usbmodem21301', baud_rate=9600):
        super().__init__()
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.thread = None

    def start(self):
        """발키보드 모니터링 시작"""
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
            self.running = True
            self.thread = threading.Thread(target=self._monitor_foot_switch, daemon=True)
            self.thread.start()
            print(f"발키보드 모니터링 시작: {self.serial_port}")
            return True
        except Exception as e:
            print(f"발키보드 연결 실패: {e}")
            return False

    def stop(self):
        """발키보드 모니터링 중지"""
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)

    def _monitor_foot_switch(self):
        """발키보드 입력을 모니터링하는 스레드"""
        while self.running:
            try:
                if self.ser and self.ser.is_open:
                    line = self.ser.readline().decode('utf-8').strip()
                    if line == "PRESSED":
                        print("발키보드 눌림 감지!")
                        self.foot_switch_pressed.emit()
                        time.sleep(0.3)  # 중복 방지 딜레이
            except Exception as e:
                if self.running:  # 종료 중이 아닐 때만 에러 출력
                    print(f"발키보드 읽기 오류: {e}")
                time.sleep(0.1)


class CameraApp(QWidget):
    def __init__(self):
        super().__init__()
        # 발키보드 상태 관리
        self.foot_switch_state = 0  # 0: 녹화 대기, 1: 녹화 중, 2: 번역 대기

        # MediaPipe 설정
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        # 모델 로드
        try:
            self.model = tf.keras.models.load_model('test1.keras')
            print("모델 로드 성공!")
            # 모델 입력 형태 확인
            input_shape = self.model.input_shape
            print(f"모델 입력 형태: {input_shape}")
        except Exception as e:
            print(f"모델 로드 실패: {e}")
            self.model = None

        self.recording = False
        self.hand_landmarks_sequence = []  # 손 랜드마크 시퀀스 저장

        # 발키보드 핸들러 초기화
        self.foot_switch_handler = FootSwitchHandler()
        self.foot_switch_handler.foot_switch_pressed.connect(self.handle_foot_switch)

        self.setWindowTitle('수어 번역 시스템 (발키보드 연동)')
        self.setGeometry(100, 100, 1000, 600)

        self.main_layout = QHBoxLayout(self)

        # 왼쪽 레이아웃 (카메라 + 인식 결과)
        self.left_layout = QVBoxLayout()
        self.camera_label = QLabel(self)
        self.camera_label.setFixedHeight(480)

        # 녹화 제어 버튼 (수동 제어용으로 유지)
        self.recording_layout = QHBoxLayout()
        self.record_button = QPushButton('녹화 시작', self)
        self.record_button.clicked.connect(self.toggle_recording)
        self.record_button.setStyleSheet("background-color: green; color: white; font-weight: bold;")

        self.translate_button = QPushButton('번역하기', self)
        self.translate_button.clicked.connect(self.translate_sign)
        self.translate_button.setEnabled(False)

        self.recording_layout.addWidget(self.record_button)
        self.recording_layout.addWidget(self.translate_button)

        # 번역 결과 텍스트 박스 - 내용이 누적되도록 수정
        self.text_edit_left = QTextEdit(self)
        self.text_edit_left.setFixedHeight(120)
        self.text_edit_left.setStyleSheet("font-size: 18pt;")
        self.text_edit_left.setReadOnly(True)

        self.left_layout.addWidget(self.camera_label)
        self.left_layout.addLayout(self.recording_layout)
        self.left_layout.addWidget(self.text_edit_left)

        # 오른쪽 레이아웃 (텍스트 + 버튼)
        self.right_layout = QVBoxLayout()

        self.text_edit_right = QTextEdit(self)
        self.text_edit_right.setFixedHeight(360)
        self.text_edit_right.setStyleSheet("font-size: 18pt;")

        self.button_layout = QVBoxLayout()
        self.increase_font_button = QPushButton('+', self)
        self.increase_font_button.clicked.connect(self.increase_font_size)
        self.decrease_font_button = QPushButton('-', self)
        self.decrease_font_button.clicked.connect(self.decrease_font_size)

        self.button_layout.addWidget(self.increase_font_button)
        self.button_layout.addWidget(self.decrease_font_button)
        self.button_layout.setAlignment(Qt.AlignTop | Qt.AlignRight)

        self.text_control_layout = QVBoxLayout()
        self.speak_again_button = QPushButton('다시 말해주세요.', self)
        self.speak_again_button.clicked.connect(lambda: self.append_text("다시 말해주세요."))
        self.wait_button = QPushButton('잠시 기다려주세요.', self)
        self.wait_button.clicked.connect(lambda: self.append_text("잠시 기다려주세요."))
        self.end_consult_button = QPushButton('진료가 끝났습니다.', self)
        self.end_consult_button.clicked.connect(lambda: self.append_text("진료가 끝났습니다."))

        # 번역 결과 지우기 버튼 추가
        self.clear_button = QPushButton('번역 결과 지우기', self)
        self.clear_button.clicked.connect(self.clear_translation_results)
        self.clear_button.setStyleSheet("background-color: orange; color: white;")

        self.text_control_layout.addWidget(self.speak_again_button)
        self.text_control_layout.addWidget(self.wait_button)
        self.text_control_layout.addWidget(self.end_consult_button)
        self.text_control_layout.addWidget(self.clear_button)

        self.right_layout.addLayout(self.button_layout)
        self.right_layout.addWidget(self.text_edit_right)
        self.right_layout.addLayout(self.text_control_layout)

        self.main_layout.addLayout(self.left_layout)
        self.main_layout.addLayout(self.right_layout)

        # 상태 표시 레이블
        self.status_label = QLabel("대기 중 - 발키보드를 눌러 녹화를 시작하세요", self)
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.left_layout.addWidget(self.status_label)

        # 카메라 초기화
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            QMessageBox.critical(self, "오류", "카메라를 열 수 없습니다.")
            sys.exit()

        # 카메라 프레임 업데이트 타이머
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)  # 30ms마다 업데이트 (약 33fps)

        # 수어 클래스명 수정 - 실제 모델의 클래스와 일치하게 설정
        self.label_map = {
            0: '아파서 못 참을 것 같아요.',
            1: '무릎 인대를 다친 것 같아요.',
            2: '유리가 깨져서 발을 다쳤어요.',
            3: '눈에 이물질이 들어갔어요.'
        }

        # 발키보드 모니터링 시작
        if self.foot_switch_handler.start():
            self.status_label.setText("발키보드 연결됨 - 발키보드를 눌러 녹화를 시작하세요")
        else:
            self.status_label.setText("발키보드 연결 실패 - 수동 버튼을 사용하세요")

    def handle_foot_switch(self):
        """발키보드 입력 처리"""
        if self.foot_switch_state == 0:  # 녹화 대기 -> 녹화 시작
            self.start_recording()
            self.foot_switch_state = 1
        elif self.foot_switch_state == 1:  # 녹화 중 -> 녹화 중지 및 번역
            self.stop_recording_and_translate()
            self.foot_switch_state = 2
        elif self.foot_switch_state == 2:  # 번역 완료 -> 다시 녹화 대기
            self.foot_switch_state = 0
            self.status_label.setText("발키보드를 눌러 다음 녹화를 시작하세요")

    def start_recording(self):
        """녹화 시작"""
        self.hand_landmarks_sequence = []  # 랜드마크 시퀀스 초기화
        self.recording = True
        self.record_button.setText("녹화 중지")
        self.record_button.setStyleSheet("background-color: red; color: white; font-weight: bold;")
        self.status_label.setText("녹화 중... (발키보드를 다시 눌러 중지)")
        self.translate_button.setEnabled(False)

    def stop_recording_and_translate(self):
        """녹화 중지 및 자동 번역"""
        self.recording = False
        self.record_button.setText("녹화 시작")
        self.record_button.setStyleSheet("background-color: green; color: white; font-weight: bold;")

        if len(self.hand_landmarks_sequence) == 0:
            self.status_label.setText("녹화된 프레임이 없습니다. 발키보드를 눌러 다시 시도하세요")
            self.foot_switch_state = 0
        else:
            self.status_label.setText(f"녹화 완료 (프레임 수: {len(self.hand_landmarks_sequence)}) - 번역 중...")
            # 자동으로 번역 수행
            QTimer.singleShot(500, self.translate_sign)  # 500ms 후 번역 실행

    def toggle_recording(self):
        """수동 녹화 토글 (기존 기능 유지)"""
        if not self.recording:
            self.start_recording()
        else:
            # 녹화 중지
            self.recording = False
            self.record_button.setText("녹화 시작")
            self.record_button.setStyleSheet("background-color: green; color: white; font-weight: bold;")
            self.status_label.setText(f"녹화 완료 (프레임 수: {len(self.hand_landmarks_sequence)})")

            # 녹화된 프레임이 없으면 경고
            if len(self.hand_landmarks_sequence) == 0:
                self.status_label.setText("녹화된 프레임이 없습니다.")
            else:
                self.translate_button.setEnabled(True)

    def update_frame(self):
        ret, frame = self.cap.read()
        if ret:
            # 좌우 반전 (거울 모드)
            frame = cv2.flip(frame, 1)

            h, w, ch = frame.shape
            target_width = 600
            target_height = 480
            aspect_ratio = w / h

            if aspect_ratio > target_width / target_height:
                new_width = target_width
                new_height = int(target_width / aspect_ratio)
            else:
                new_height = target_height
                new_width = int(target_height * aspect_ratio)

            resized_frame = cv2.resize(frame, (new_width, new_height))
            frame_with_padding = np.full((target_height, target_width, 3), 255, dtype=np.uint8)
            start_x = (target_width - new_width) // 2
            start_y = (target_height - new_height) // 2
            frame_with_padding[start_y:start_y + new_height, start_x:start_x + new_width] = resized_frame

            # MediaPipe로 손 랜드마크 처리
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.hands.process(rgb_frame)

            # 랜드마크 그리기
            display_frame = frame_with_padding.copy()
            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    self.mp_drawing.draw_landmarks(
                        display_frame,
                        hand_landmarks,
                        self.mp_hands.HAND_CONNECTIONS,
                        self.mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=4),
                        self.mp_drawing.DrawingSpec(color=(0, 0, 255), thickness=2, circle_radius=2)
                    )

                # 녹화 중일 때 랜드마크 저장
                if self.recording:
                    landmarks_data = self.extract_hand_landmarks(results)
                    self.hand_landmarks_sequence.append(landmarks_data)

            # 녹화 중일 때 표시
            if self.recording:
                cv2.putText(display_frame, "REC", (20, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                cv2.circle(display_frame, (65, 25), 10, (0, 0, 255), -1)

            # 디스플레이용 RGB 변환
            rgb_display = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_display.shape
            bytes_per_line = ch * w
            qimg = QImage(rgb_display.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            self.camera_label.setPixmap(pixmap)

    def extract_hand_landmarks(self, results):
        """MediaPipe 결과에서 손 랜드마크 추출"""
        landmarks_data = []

        # 양손 처리 (최대 2개)
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                # 21개 랜드마크 각각 x, y, z 좌표 추출
                for landmark in hand_landmarks.landmark:
                    landmarks_data.extend([landmark.x, landmark.y, landmark.z])

        # 랜드마크가 없는 경우나 부족한 경우 0으로 패딩 (126 = 21개 점 * 3좌표 * 최대 2개 손)
        while len(landmarks_data) < 126:
            landmarks_data.append(0.0)

        # 126개로 고정 (초과하는 경우 자르기)
        return landmarks_data[:126]

    def preprocess_sequence(self):
        """녹화된 랜드마크 시퀀스를 모델 입력에 맞게 전처리"""
        if not self.hand_landmarks_sequence:
            return None

        try:
            # 모델 예상 입력: (batch_size, sequence_length=300, features=126)
            target_sequence_length = 300

            # 시퀀스 길이 조정
            if len(self.hand_landmarks_sequence) < target_sequence_length:
                # 부족한 경우 마지막 프레임으로 패딩
                last_landmarks = self.hand_landmarks_sequence[-1] if self.hand_landmarks_sequence else [0.0] * 126
                padding = [last_landmarks] * (target_sequence_length - len(self.hand_landmarks_sequence))
                features_sequence = self.hand_landmarks_sequence + padding
            else:
                # 많은 경우 균등하게 샘플링
                indices = np.linspace(0, len(self.hand_landmarks_sequence) - 1, target_sequence_length, dtype=int)
                features_sequence = [self.hand_landmarks_sequence[i] for i in indices]

            # 최종 형태로 변환: (batch_size=1, sequence_length=300, features=126)
            sequence = np.array(features_sequence, dtype=np.float32)
            sequence = np.expand_dims(sequence, axis=0)  # 배치 차원 추가

            self.status_label.setText(f"전처리 완료: 입력 형태 {sequence.shape}")
            return sequence

        except Exception as e:
            self.status_label.setText(f"전처리 오류: {str(e)}")
            return None

    def translate_sign(self):
        """수어 번역 수행"""
        if self.model is None:
            self.append_translation_result("모델이 로드되지 않았습니다.")
            return

        self.status_label.setText("번역 중...")

        # 랜드마크 시퀀스 전처리
        processed_sequence = self.preprocess_sequence()
        if processed_sequence is None:
            self.append_translation_result("데이터 처리에 실패했습니다.")
            return

        try:
            # 모델 예측
            predictions = self.model.predict(processed_sequence)

            # 예측 결과 해석
            predicted_class_idx = np.argmax(predictions[0])
            confidence = predictions[0][predicted_class_idx]

            # 레이블 맵을 사용하여 클래스 이름 가져오기
            if predicted_class_idx in self.label_map:
                predicted_sign = self.label_map[predicted_class_idx]
                result_text = predicted_sign  # 확률 정보 제거
            else:
                result_text = f"알 수 없는 수어 (클래스 인덱스: {predicted_class_idx})"

            # 결과를 누적하여 표시
            self.append_translation_result(result_text)

            if self.foot_switch_state == 2:
                self.status_label.setText("번역 완료 - 발키보드를 눌러 다음 녹화를 시작하세요")
            else:
                self.status_label.setText("번역 완료")

        except Exception as e:
            self.append_translation_result(f"예측 오류: {str(e)}")
            self.status_label.setText("번역 실패")

    def append_translation_result(self, text):
        """번역 결과를 누적하여 추가"""
        if self.text_edit_left.toPlainText():
            self.text_edit_left.append(text)
        else:
            self.text_edit_left.setText(text)

    def clear_translation_results(self):
        """번역 결과 지우기"""
        self.text_edit_left.clear()

    def increase_font_size(self):
        current_font_size = int(self.text_edit_left.styleSheet().split(': ')[1].split('pt')[0])
        new_font_size = min(current_font_size + 2, 40)
        self.text_edit_left.setStyleSheet(f"font-size: {new_font_size}pt;")
        self.text_edit_right.setStyleSheet(f"font-size: {new_font_size}pt;")

    def decrease_font_size(self):
        current_font_size = int(self.text_edit_left.styleSheet().split(': ')[1].split('pt')[0])
        new_font_size = max(current_font_size - 2, 8)
        self.text_edit_left.setStyleSheet(f"font-size: {new_font_size}pt;")
        self.text_edit_right.setStyleSheet(f"font-size: {new_font_size}pt;")

    def append_text(self, text):
        self.text_edit_right.append(text)

    def closeEvent(self, event):
        self.foot_switch_handler.stop()
        self.cap.release()
        self.hands.close()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = CameraApp()
    window.show()
    sys.exit(app.exec_())