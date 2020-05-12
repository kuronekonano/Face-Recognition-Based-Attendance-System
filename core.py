#!/usr/bin/env python3
# Author: kuronekonano <god772525182@gmail.com>
import dlib
import pymysql
import telegram
import cv2
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from PyQt5.QtCore import QTimer, QThread, pyqtSignal, QRegExp, Qt
from PyQt5.QtGui import QImage, QPixmap, QIcon, QTextCursor, QRegExpValidator
from PyQt5.QtWidgets import QDialog, QApplication, QMainWindow, QMessageBox, QAbstractItemView, QTableWidgetItem
from PyQt5.uic import loadUi

import os
import webbrowser
import logging
import logging.config
import sys
import threading
import queue
import multiprocessing
import winsound
import numpy
import csv

from configparser import ConfigParser
from datetime import datetime

from dataRecord import DataRecordUI

fontStyle = ImageFont.truetype(
    "微软雅黑Bold.ttf", 20, encoding="utf-8")  # 字体格式

haar_faceCascade = cv2.CascadeClassifier('./haarcascades/haarcascade_frontalface_default.xml')  # haar级联分类器脸部捕获器
haar_eyes_cascade = cv2.CascadeClassifier('./haarcascades/haarcascade_eye.xml')  # 眼部识别
haar_smile_cascade = cv2.CascadeClassifier('./haarcascades/haarcascade_smile.xml')  # 微笑识别
predictor_5 = dlib.shape_predictor('./shape_predictor_5_face_landmarks.dat')  # 5特征点模型
predictor_68 = dlib.shape_predictor('./shape_predictor_68_face_landmarks.dat')  # 68特征点模型
facerec = dlib.face_recognition_model_v1("dlib_face_recognition_resnet_model_v1.dat")  # 人脸识别器模型
dlib_detector = dlib.get_frontal_face_detector()  # dlib 人脸检测器


# 中文名渲染
def cv2ImgAddText(img, text, left, top, text_color=(0, 0, 255)):
    if isinstance(img, numpy.ndarray):  # 判断是否OpenCV图片类型
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    # 创建一个可以在给定图像上绘图的对象
    draw = ImageDraw.Draw(img)
    # 绘制文本
    draw.text((left, top), text, text_color, font=fontStyle)
    # 转换回OpenCV格式
    return cv2.cvtColor(numpy.asarray(img), cv2.COLOR_RGB2BGR)


def connect_to_sql():
    conn = pymysql.connect(host='localhost',
                           user='root',
                           password='970922',
                           db='mytest',
                           port=3306,
                           charset='utf8')
    cursor = conn.cursor()
    return conn, cursor


# 找不到已训练的人脸数据文件,错误类
class TrainingDataNotFoundError(FileNotFoundError):
    pass


# 找不到数据库文件，错误类
class DatabaseNotFoundError(FileNotFoundError):
    pass


class CoreUI(QMainWindow):
    database = 'users'  # sqlite 数据库路径，存储学生信息文本
    trainingData = './recognizer/trainingData.yml'  # 训练数据路径【由数据录入时生成】
    dlib_features_data = './dlib_128D_csv/features_all.csv'  # dlib人脸特征数据
    cap = cv2.VideoCapture()  # OpenCV获取视频源方法
    captureQueue = queue.Queue()  # 图像队列
    alarmQueue = queue.LifoQueue()  # 报警队列，后进先出
    attendance_queue = queue.Queue()
    logQueue = multiprocessing.Queue()  # 日志队列，用于同步所有功能多进程状态
    receiveLogSignal = pyqtSignal(str)  # LOG信号

    def __init__(self):
        super(CoreUI, self).__init__()
        self.timer = QTimer(self)  # 定时器实例化
        self.faceProcessingThread = FaceProcessingThread()  # OpenCV处理线程实例化
        self.isExternalCameraUsed = False  # 默认不使用外接摄像头
        loadUi('./ui/Core.ui', self)  # 读取qtUI配置
        self.setWindowIcon(QIcon('./icons/icon.png'))  # 设置窗口图标
        self.setFixedSize(1700, 900)  # 窗口大小
        self.InitUI()

    def InitUI(self):
        # 图像捕获
        self.useExternalCameraCheckBox.stateChanged.connect(
            lambda: self.useExternalCamera(self.useExternalCameraCheckBox))  # 按钮初始化绑定 更新外接摄像头按钮状态

        self.startWebcamButton.toggled.connect(self.startWebcam)  # 按钮绑定开启摄像头逻辑
        self.startWebcamButton.setCheckable(True)

        # 创建班级
        self.CreateClasspushButton.clicked.connect(self.create_class)

        # 数据库按钮绑定
        self.initDbButton.setIcon(QIcon('./icons/warning.png'))  # 数据警告图标
        self.initDbButton.clicked.connect(self.initDb)  # 按钮绑定数据库初始化函数

        # 定时器用于对QTUI画面进行定期更新，camera画面的图片需要实时更新
        # 定时器每5ms更新摄像头帧画面，此处绑定定时器绑定更新函数
        self.timer.timeout.connect(self.updateFrame)

        # 功能开关
        self.faceTrackerCheckBox.stateChanged.connect(
            lambda: self.faceProcessingThread.enableFaceTracker(self))  # 人脸检测,ui默认开启
        self.faceRecognizerCheckBox.stateChanged.connect(
            lambda: self.faceProcessingThread.enableFaceRecognizer(self))  # 人脸识别，ui默认不开启，默认不可用
        self.panalarmCheckBox.stateChanged.connect(
            lambda: self.faceProcessingThread.enablePanalarm(self))  # 报警系统，ui默认开启
        self.haar_faceTrackerCheckBox.stateChanged.connect(
            lambda: self.faceProcessingThread.enable_haar_faceCascade(self))

        # 直方图均衡化
        self.equalizeHistCheckBox.stateChanged.connect(
            lambda: self.faceProcessingThread.enableEqualizeHist(self))

        # 调试模式
        self.debugCheckBox.stateChanged.connect(lambda: self.faceProcessingThread.enableDebug(self))  # 调试模式开关绑定
        self.confidenceThresholdSlider.valueChanged.connect(
            lambda: self.faceProcessingThread.setConfidenceThreshold(self))  # 调试模式相似度阈值控制绑定
        self.autoAlarmThresholdSlider.valueChanged.connect(
            lambda: self.faceProcessingThread.setAutoAlarmThreshold(self))  # 调试模式置信度阈值绑定

        # 签到系统
        self.recieveAlarm = RecieveAlarm(self)  # 签到线程实例化
        self.bellCheckBox.stateChanged.connect(lambda: self.recieveAlarm.enableBell(self))  # 设备发声控制绑定
        self.telegramBotPushCheckBox.stateChanged.connect(
            lambda: self.recieveAlarm.enableTelegramBotPush(self))  # 截图推送控制绑定
        self.telegramBotSettingsButton.clicked.connect(self.telegramBotSettings)  # 推送配置控制绑定

        # 帮助与支持
        self.viewGithubRepoButton.clicked.connect(
            lambda: webbrowser.open('https://github.com/kuronekonano/Face-Recognition-Based-Attendance-System/'))
        self.contactDeveloperButton.clicked.connect(lambda: webbrowser.open('https://t.me/kuronekonano'))

        # 日志系统
        self.receiveLogSignal.connect(lambda log: self.logOutput(log))  # 日志系统信号绑定输出功能
        self.logOutputThread = threading.Thread(target=self.receiveLog, daemon=True)
        self.logOutputThread.start()  # 日志监听线程

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    # 检查数据库状态
    def initDb(self):
        try:
            conn, cursor = connect_to_sql()

            if not DataRecordUI.table_exists(cursor, 'user'):  # 检查学生信息数据库
                raise DatabaseNotFoundError
            if not os.path.isfile(self.trainingData):  # 检查训练数据
                raise TrainingDataNotFoundError

            cursor.execute('SELECT Count(*) FROM users')  # 查询数据库人数
            result = cursor.fetchone()
            dbUserCount = result[0]
        except DatabaseNotFoundError:
            logging.error('系统找不到数据库表{}'.format('users'))
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：未发现数据库文件，你可能未进行人脸采集')
        except TrainingDataNotFoundError:
            logging.error('系统找不到已训练的人脸数据{}'.format(self.trainingData))
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：未发现已训练的人脸数据文件，请完成训练后继续')
        except Exception as e:
            logging.error('读取数据库异常，无法完成数据库初始化')
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：读取数据库异常，初始化数据库失败')
        else:
            cursor.close()
            conn.close()
            if not dbUserCount > 0:
                logging.warning('数据库为空')
                self.logQueue.put('warning：数据库为空，人脸识别功能不可用')
                self.initDbButton.setIcon(QIcon('./icons/warning.png'))  # 数据库为空时可重复初始化
            else:
                self.logQueue.put('Success：数据库状态正常，发现用户数：{}'.format(dbUserCount))  # 数据库状态信息插入日志队列
                self.initDbButton.setIcon(QIcon('./icons/success.png'))  # 修改图标
                self.initDbButton.setEnabled(False)  # 只允许初始化一次数据库，之后按钮变为不可用
                self.faceRecognizerCheckBox.setToolTip('须先开启人脸跟踪')  # 修改人脸识别复选框提示符
                self.faceRecognizerCheckBox.setEnabled(True)  # 启用人脸识别开关
                self.CreateClasspushButton.setEnabled(True)  # 启用创建名单开关

    # 创建课程/班级签到表
    def create_class(self):
        self.create_class_dialog = CreatClassDialog()
        self.create_class_dialog.CreatepushButton.clicked.connect(self.save_table)
        self.create_class_dialog.exec()

    # 保存表并提交数据库逻辑
    def save_table(self):
        self.class_name = self.create_class_dialog.ClassNameLineEdit.text().strip()
        if self.class_name == '':
            text = '课程或班级名称为空！'
            informativeText = '<b>请输入课程或班级名称。</b>'
            CoreUI.callDialog(QMessageBox.Critical, text, informativeText, QMessageBox.Ok)
            return
        conn, cursor = connect_to_sql()
        if DataRecordUI.table_exists(cursor, self.class_name):
            text = '该表名已存在'
            informativeText = '<b>请重新输入课程或班级名称（可附加日期时间或序号区分）。</b>'
            CoreUI.callDialog(QMessageBox.Critical, text, informativeText, QMessageBox.Ok)
            return
        try:
            if not DataRecordUI.table_exists(cursor, self.class_name):  # 判断表格是否重复
                sql = '''CREATE TABLE IF NOT EXISTS `%s` (
                                          stu_id VARCHAR(20) PRIMARY KEY NOT NULL,
                                          cn_name VARCHAR(30) NOT NULL,
                                          attendance int(2) DEFAULT 0,
                                          attendance_time DATETIME DEFAULT NULL
                                          )''' % self.class_name
                cursor.execute(sql)  # 单次签到建表
            row_num = self.create_class_dialog.AddStuTable.rowCount()
            for row in range(row_num):
                stu_id = self.create_class_dialog.AddStuTable.item(row, 0).text()  # 学号
                cn_name = self.create_class_dialog.AddStuTable.item(row, 1).text()  # 姓名
                sql_judge = 'select stu_id from `%s` where stu_id="%s"' % (self.class_name, stu_id)
                if not CoreUI.check_id_exists(cursor, sql_judge):
                    insert_sql = '''INSERT INTO `%s` (stu_id, cn_name) VALUES ("%s", "%s")''' % (
                        self.class_name, stu_id, cn_name)
                    cursor.execute(insert_sql)
                    update_user_course_count = 'UPDATE `users` SET total_course_count=total_course_count+1 WHERE stu_id="%s"' % stu_id
                    cursor.execute(update_user_course_count)
        except Exception as e:
            logging.error('读取数据库异常，无法完成数据存储')
            CoreUI.logQueue.put('Error：数据存储失败')
            print(e)
        else:
            CoreUI.logQueue.put('Success：表格创建完成')
        finally:
            cursor.close()
            conn.commit()
            conn.close()

        self.create_class_dialog.close()

        if not self.panalarmCheckBox.isEnabled():
            self.panalarmCheckBox.setEnabled(True)  # 签到系统启用

    # 是否使用外接摄像头
    def useExternalCamera(self, useExternalCameraCheckBox):
        if useExternalCameraCheckBox.isChecked():
            self.isExternalCameraUsed = True
        else:
            self.isExternalCameraUsed = False

    # 打开/关闭摄像头
    def startWebcam(self, status):
        if status:
            if not self.cap.isOpened():  # 开启摄像头，判断视频源选项
                camID = 1 if self.isExternalCameraUsed else 0 + cv2.CAP_DSHOW
                self.cap.open(camID)  # 开启视频源摄像头
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)  # 视频流的宽高
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                ret, frame = self.cap.read()  # 逐帧捕捉

                if not ret:
                    logging.error('无法调用电脑摄像头{}'.format(camID))
                    self.logQueue.put('Error：初始化摄像头失败')
                    self.cap.release()
                    self.startWebcamButton.setIcon(QIcon('./icons/error.png'))
                else:
                    self.timer.start(5)  # 启动定时器,每5ms刷新一次
                    self.faceProcessingThread.start()  # 启动OpenCV图像处理线程
                    self.recieveAlarm.start()  # 启动签到系统线程
                    self.startWebcamButton.setIcon(QIcon('./icons/success.png'))
                    self.startWebcamButton.setText('关闭摄像头')
        else:  # 关闭摄像头
            self.faceProcessingThread.stop()
            self.recieveAlarm.stop()
            if self.cap.isOpened():
                if self.timer.isActive():
                    self.timer.stop()
                self.cap.release()  # 释放摄像头控制

                self.realTimeCaptureLabel.clear()
                self.realTimeCaptureLabel.setText('<font color=red>摄像头未开启</font>')
                self.startWebcamButton.setText('打开摄像头')
                # self.startWebcamButton.setText('摄像头已关闭')  # 当存在报警线程时启用
                # self.startWebcamButton.setEnabled(False)
                self.startWebcamButton.setIcon(QIcon())
                self.captureQueue.queue.clear()

    # 定时器，实时更新画面
    def updateFrame(self):
        if self.cap.isOpened():
            if not self.captureQueue.empty():
                captureData = self.captureQueue.get()
                realTimeFrame = captureData.get('realTimeFrame')
                self.displayImage(realTimeFrame, self.realTimeCaptureLabel)

    # 显示图片
    def displayImage(self, img, qlabel):
        # BGR -> RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # img = cv2.flip(img, 1)
        # default：The image is stored using 8-bit indexes into a colormap， for example：a gray image
        qformat = QImage.Format_Indexed8

        if len(img.shape) == 3:  # rows[0], cols[1], channels[2]
            if img.shape[2] == 4:
                # The image is stored using a 32-bit byte-ordered RGBA format (8-8-8-8)
                # A: alpha channel，不透明度参数。如果一个像素的alpha通道数值为0%，那它就是完全透明的
                qformat = QImage.Format_RGBA8888
            else:
                qformat = QImage.Format_RGB888

        # img.shape[1]：图像宽度width，img.shape[0]：图像高度height，img.shape[2]：图像通道数
        # QImage.__init__ (self, bytes data, int width, int height, int bytesPerLine, Format format)
        # 从内存缓冲流获取img数据构造QImage类
        # img.strides[0]：每行的字节数（width*3）,rgb为3，rgba为4
        # strides[0]为最外层(即一个二维数组所占的字节长度)，strides[1]为次外层（即一维数组所占字节长度），strides[2]为最内层（即一个元素所占字节长度）
        # 从里往外看，strides[2]为1个字节长度（uint8），strides[1]为3*1个字节长度（3即rgb 3个通道）
        # strides[0]为width*3个字节长度，width代表一行有几个像素

        outImage = QImage(img, img.shape[1], img.shape[0], img.strides[0], qformat)
        qlabel.setPixmap(QPixmap.fromImage(outImage))
        qlabel.setScaledContents(True)  # 图片自适应大小

    # TelegramBot设置
    def telegramBotSettings(self):
        cfg = ConfigParser()
        cfg.read('./config/telegramBot.cfg', encoding='utf-8-sig')
        read_only = cfg.getboolean('telegramBot', 'read_only')
        # read_only = False
        if read_only:
            text = '基于安全考虑，系统拒绝了本次请求。'
            informativeText = '<b>请联系设备管理员。</b>'
            CoreUI.callDialog(QMessageBox.Critical, text, informativeText, QMessageBox.Ok)
        else:
            token = cfg.get('telegramBot', 'token')
            chat_id = cfg.get('telegramBot', 'chat_id')
            proxy_url = cfg.get('telegramBot', 'proxy_url')
            message = cfg.get('telegramBot', 'message')

            self.telegramBotDialog = TelegramBotDialog()
            self.telegramBotDialog.tokenLineEdit.setText(token)
            self.telegramBotDialog.telegramIDLineEdit.setText(chat_id)
            self.telegramBotDialog.socksLineEdit.setText(proxy_url)
            self.telegramBotDialog.messagePlainTextEdit.setPlainText(message)
            self.telegramBotDialog.exec()

    # 写入CSV文件存档
    @staticmethod
    def write_csv(csv_path, csv_data):
        with open(csv_path, 'a+', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(csv_data)

    # 创建CSV文件文档
    @staticmethod
    def create_csv(path):
        with open(path, 'w', newline='') as file:
            writer = csv.writer(file)
            csv_head = ["学号", "姓名", "签到时间"]
            writer.writerow(csv_head)

    @staticmethod
    def check_id_exists(cursor, sql_judge):
        cursor.execute(sql_judge)
        judge_id = cursor.fetchone()
        if judge_id is None:
            return False
        return True

    @staticmethod
    def write_sql(class_name, stu_id, timestamp):
        # print(class_name, stu_id, timestamp)
        conn, cursor = connect_to_sql()
        try:
            if DataRecordUI.table_exists(cursor, class_name):  # 表格存在检测
                sql_judge = 'select stu_id from `%s` where stu_id="%s"' % (class_name, stu_id)
                if CoreUI.check_id_exists(cursor, sql_judge):  # 学生存在确认
                    update_sql = 'UPDATE `%s` SET attendance="%s", attendance_time="%s" WHERE stu_id="%s"' % (
                        class_name, 1, timestamp, stu_id)
                    cursor.execute(update_sql)
                    update_user_sql = 'UPDATE `users` SET total_attendance_times=total_attendance_times+1 WHERE stu_id="%s"' % stu_id
                    cursor.execute(update_user_sql)
        except Exception as e:
            logging.error('读取数据库异常，无法完成数据存储')
            CoreUI.logQueue.put('Error：数据存储失败')
            print(e)
        else:
            logging.info('Success：学生：{}完成签到！数据库存储完成'.format(stu_id))
        finally:
            cursor.close()
            conn.commit()
            conn.close()

    # 设备响铃进程
    @staticmethod
    def bellProcess(queue):
        logQueue = queue  # 参数是一个日志队列，用于同步所有进程的日志信息
        logQueue.put('Info：设备正在响铃...')
        winsound.PlaySound('./eshop.wav', winsound.SND_FILENAME)  # 调用音频

    # TelegramBot推送进程
    @staticmethod
    def telegramBotPushProcess(queue, img=None):
        logQueue = queue
        cfg = ConfigParser()
        try:
            cfg.read('./config/telegramBot.cfg', encoding='utf-8-sig')

            # 读取TelegramBot配置
            token = cfg.get('telegramBot', 'token')
            chat_id = cfg.getint('telegramBot', 'chat_id')
            proxy_url = cfg.get('telegramBot', 'proxy_url')
            message = cfg.get('telegramBot', 'message')

            # 是否使用代理
            if proxy_url:
                proxy = telegram.utils.request.Request(proxy_url=proxy_url)
                bot = telegram.Bot(token=token, request=proxy)
            else:
                bot = telegram.Bot(token=token)

            bot.send_message(chat_id=chat_id, text=message)

            # 发送疑似陌生人脸截屏到Telegram
            if img:
                bot.send_photo(chat_id=chat_id, photo=open(img, 'rb'), timeout=10)
        except Exception as e:
            logQueue.put('Error：TelegramBot推送失败')
            print(e)
        else:
            logQueue.put('Success：TelegramBot推送成功')

    # 系统日志服务常驻，接收并处理系统日志
    def receiveLog(self):
        while True:  # 不断接受日志队列内容，只要不为空就输出信息
            data = self.logQueue.get()
            if data:
                self.receiveLogSignal.emit(data)  # 发射信号

    # LOG输出，参数为日志文本信息
    def logOutput(self, log):
        # 获取当前系统时间
        time = datetime.now().strftime('[%Y/%m/%d %H:%M:%S]')
        log = time + ' ' + log + '\n'  # 构造日志整体信息，包含时间以及主题内容

        self.logTextEdit.moveCursor(QTextCursor.End)  # 移动光标置文本框底端
        self.logTextEdit.insertPlainText(log)  # 插入日志文本内容
        self.logTextEdit.ensureCursorVisible()  # 自动滚屏

    # 系统对话框
    @staticmethod
    def callDialog(icon, text, informativeText, standardButtons, defaultButton=None):
        msg = QMessageBox()
        msg.setWindowIcon(QIcon('./icons/icon.png'))
        msg.setWindowTitle('OpenCV Face Recognition System - Core')
        msg.setIcon(icon)
        msg.setText(text)
        msg.setInformativeText(informativeText)
        msg.setStandardButtons(standardButtons)
        if defaultButton:
            msg.setDefaultButton(defaultButton)
        return msg.exec()

    # 窗口关闭事件，关闭OpenCV线程、定时器、摄像头
    def closeEvent(self, event):
        if self.faceProcessingThread.isRunning:
            self.faceProcessingThread.stop()
        if self.timer.isActive():
            self.timer.stop()
        if self.cap.isOpened():
            self.cap.release()
        event.accept()


# TelegramBot设置对话框
def telegramBotTest(token, proxy_url):
    try:
        # 是否使用代理
        if proxy_url:
            proxy = telegram.utils.request.Request(proxy_url=proxy_url)
            bot = telegram.Bot(token=token, request=proxy)
        else:
            bot = telegram.Bot(token=token)
        bot.get_me()
    except Exception as e:
        return False
    else:
        return True


class TelegramBotDialog(QDialog):
    def __init__(self):
        super(TelegramBotDialog, self).__init__()
        loadUi('./ui/TelegramBotDialog.ui', self)
        self.setWindowIcon(QIcon('./icons/icon.png'))
        self.setFixedSize(550, 358)

        chat_id_regx = QRegExp('^\d+$')
        chat_id_validator = QRegExpValidator(chat_id_regx, self.telegramIDLineEdit)
        self.telegramIDLineEdit.setValidator(chat_id_validator)

        self.okButton.clicked.connect(self.telegramBotSettings)

    def telegramBotSettings(self):
        # 获取用户输入
        token = self.tokenLineEdit.text().strip()
        chat_id = self.telegramIDLineEdit.text().strip()
        proxy_url = self.socksLineEdit.text().strip()
        message = self.messagePlainTextEdit.toPlainText().strip()

        # 校验并处理用户输入
        if not (token and chat_id and message):
            self.okButton.setIcon(QIcon('./icons/error.png'))
            CoreUI.logQueue.put('Error：API Token、Telegram ID和消息内容为必填项')
        else:
            ret = telegramBotTest(token, proxy_url)
            if ret:
                cfg_file = './config/telegramBot.cfg'
                cfg = ConfigParser()
                cfg.read(cfg_file, encoding='utf-8-sig')

                cfg.set('telegramBot', 'token', token)
                cfg.set('telegramBot', 'chat_id', chat_id)
                cfg.set('telegramBot', 'proxy_url', proxy_url)
                cfg.set('telegramBot', 'message', message)

                try:
                    with open(cfg_file, 'w', encoding='utf-8') as file:
                        cfg.write(file)
                except:
                    logging.error('写入telegramBot配置文件发生异常')
                    CoreUI.logQueue.put('Error：写入配置文件时发生异常，更新失败')
                else:
                    CoreUI.logQueue.put('Success：测试通过，系统已更新TelegramBot配置')
                    self.close()
            else:
                CoreUI.logQueue.put('Error：测试失败，无法更新TelegramBot配置')

    # TelegramBot 测试


# 签到线程
class RecieveAlarm(QThread):

    def __init__(self, core_ui):
        super(RecieveAlarm, self).__init__()
        self.isRunning = True  # 线程状态
        self.isBellEnabled = True  # 响铃开关状态
        self.alarmSignalThreshold = 10  # 队列中挤压危险帧数量，超过即发出报警阈值
        self.isTelegramBotPushEnabled = False  # 机器人bot通知
        self.core_ui = core_ui

    # 签到系统：是否允许设备响铃
    def enableBell(self, coreUI):
        if coreUI.bellCheckBox.isChecked():
            self.isBellEnabled = True
            coreUI.statusBar().showMessage('设备发声：开启')
        else:
            if self.isTelegramBotPushEnabled:
                self.isBellEnabled = False
                coreUI.statusBar().showMessage('设备发声：关闭')
            else:
                coreUI.logQueue.put('Error：操作失败，至少选择一种确认方式')
                coreUI.bellCheckBox.setCheckState(Qt.Unchecked)
                coreUI.bellCheckBox.setChecked(True)
        # print('isBellEnabled：', self.isBellEnabled)

    # 签到系统: 机器人推送
    def enableTelegramBotPush(self, coreUI):
        if coreUI.telegramBotPushCheckBox.isChecked():
            self.isTelegramBotPushEnabled = True
            coreUI.statusBar().showMessage('TelegramBot推送：开启')
        else:
            if self.isBellEnabled:
                self.isTelegramBotPushEnabled = False
                coreUI.statusBar().showMessage('TelegramBot推送：关闭')
            else:
                coreUI.logQueue.put('Error：操作失败，至少选择一种确认方式')
                coreUI.telegramBotPushCheckBox.setCheckState(Qt.Unchecked)
                coreUI.telegramBotPushCheckBox.setChecked(True)
        # print('isTelegramBotPushEnabled：', self.isTelegramBotPushEnabled)

    def run(self) -> None:
        self.isRunning = True
        while self.isRunning:
            jobs_alarm = []
            jobs_confirm = []
            # print(self.alarmQueue.qsize())
            # 陌生人预警
            if CoreUI.alarmQueue.qsize() > self.alarmSignalThreshold:  # 若报警信号触发超出既定计数，进行报警
                if not os.path.isdir('./unknown'):  # 未知人员目录检查存在
                    os.makedirs('./unknown')
                lastAlarmSignal = CoreUI.alarmQueue.get()  # 获取报警队列的某个信号
                timestamp, img = lastAlarmSignal.get('timestamp'), lastAlarmSignal.get('img')  # 获取报警时间戳、获取报警帧
                # 疑似陌生人脸，截屏存档
                cv2.imwrite('./unknown/{}.jpg'.format(timestamp), img)  # 存储截图,命名为时间戳
                logging.info('报警信号触发超出预设计数，自动报警系统已被激活')
                CoreUI.logQueue.put('Info：报警信号触发超出预设计数，自动报警系统已被激活')

                # 报警响铃
                # print('while running isBellEnabled:', self.isBellEnabled)
                # if self.isBellEnabled:
                #     p1 = multiprocessing.Process(target=CoreUI.bellProcess, args=(CoreUI.logQueue,))
                #     p1.start()  # 调用响铃进程
                #     jobs.append(p1)

                # TelegramBot推送
                # print('while running isTelegramBotPushEnabled:', self.isTelegramBotPushEnabled)
                if self.isTelegramBotPushEnabled:
                    if os.path.isfile('./unknown/{}.jpg'.format(timestamp)):
                        img = './unknown/{}.jpg'.format(timestamp)
                    else:
                        img = None
                    p2 = multiprocessing.Process(target=CoreUI.telegramBotPushProcess, args=(CoreUI.logQueue, img))
                    p2.start()
                    jobs_alarm.append(p2)

                # 等待本轮报警结束
                for p in jobs_alarm:
                    p.join()

                # 重置报警信号
                with CoreUI.alarmQueue.mutex:  # 队列互斥锁
                    CoreUI.alarmQueue.queue.clear()  # 清空报警队列

            # 签到确认
            if CoreUI.attendance_queue.qsize():
                if not os.path.isdir('./attendance_snapshot'):  # 截图目录
                    os.makedirs('./attendance_snapshot')

                if not os.path.isdir('./attendance_csv'):  # 临时存储目录
                    os.makedirs('./attendance_csv')
                arrive_signal = CoreUI.attendance_queue.get()

                csv_path = os.path.join('./attendance_csv', self.core_ui.class_name + '.csv')
                if not os.path.exists(csv_path):
                    CoreUI.create_csv(csv_path)  # 创建CSV文件

                stu_id = arrive_signal.get('id')  # 学号
                zh_name = arrive_signal.get('name')  # 姓名
                timestamp = arrive_signal.get('time')  # 时间戳
                img = arrive_signal.get('img')  # 获取签到时间戳、获取签到帧

                sql_judge = 'select stu_id from `%s` where stu_id="%s"' % (self.core_ui.class_name, stu_id)
                conn, cursor = connect_to_sql()
                # 学生在签到表中才会签到
                if CoreUI.check_id_exists(cursor, sql_judge):

                    csv_data = [stu_id, zh_name, timestamp.strftime("%Y/%m/%d %H:%M:%S")]
                    CoreUI.write_csv(csv_path, csv_data)  # 写入CSV文件
                    CoreUI.write_sql(self.core_ui.class_name, stu_id, timestamp.strftime("%Y/%m/%d %H:%M:%S"))
                    message = '{} {} 同学签到成功！'.format(stu_id, zh_name)
                    CoreUI.logQueue.put(message)
                    cv2.imwrite('./attendance_snapshot/{}.jpg'.format(timestamp.strftime('%Y%m%d%H%M%S')),
                                img)  # 存储截图,命名为时间戳
                    # logging.info('签到成功！')
                    # CoreUI.logQueue.put('Info：有新的同学签到成功，签到确认系统已被激活')

                    # 签到响铃
                    # print('while running isBellEnabled:', self.isBellEnabled)
                    if self.isBellEnabled:
                        p1 = multiprocessing.Process(target=CoreUI.bellProcess, args=(CoreUI.logQueue,))
                        p1.start()  # 调用响铃进程
                        jobs_confirm.append(p1)

                    # TelegramBot推送
                    # print('while running isTelegramBotPushEnabled:', self.isTelegramBotPushEnabled)
                    if self.isTelegramBotPushEnabled:
                        if os.path.isfile('./attendance_snapshot/{}.jpg'.format(timestamp.strftime('%Y%m%d%H%M%S'))):
                            img = './attendance_snapshot/{}.jpg'.format(timestamp.strftime('%Y%m%d%H%M%S'))
                        else:
                            img = None
                        p2 = multiprocessing.Process(target=CoreUI.telegramBotPushProcess, args=(CoreUI.logQueue, img))
                        p2.start()
                        jobs_confirm.append(p2)

                    # 等待本轮报警结束
                    for p in jobs_confirm:
                        p.join()

                    # # 重置报警信号
                    # with CoreUI.attendance_queue.mutex:  # 队列互斥锁
                    #     CoreUI.attendance_queue.queue.clear()  # 清空签到队列

    def stop(self):
        self.isRunning = False
        self.quit()
        self.wait()


# OpenCV线程
class FaceProcessingThread(QThread):
    def __init__(self):
        super(FaceProcessingThread, self).__init__()
        self.isRunning = True  # 线程运行标志

        self.isFaceTrackerEnabled = True  # 人脸追踪
        self.isFaceRecognizerEnabled = False  # 人脸识别
        self.isPanalarmEnabled = False  # 报警系统

        self.isDebugMode = False  # 调试模式
        self.confidenceThreshold = 55  # 置信度阈值
        self.autoAlarmThreshold = 65  # 报警阈值

        self.isEqualizeHistEnabled = False  # 直方图均衡化

        self.is_haar_faceCascade = False  # Haar级联分类器识别

        self.attendance_list = dict()  # 签到名单

    # 是否开启人脸跟踪
    def enableFaceTracker(self, coreUI):
        if coreUI.faceTrackerCheckBox.isChecked():  # 检查人脸追踪复选框状态
            self.isFaceTrackerEnabled = True
            coreUI.statusBar().showMessage('人脸跟踪：开启')  # 左下角状态提示栏
        else:
            self.isFaceTrackerEnabled = False
            coreUI.statusBar().showMessage('人脸跟踪：关闭')

    # 是否开启人脸识别
    def enableFaceRecognizer(self, coreUI):
        if coreUI.faceRecognizerCheckBox.isChecked():  # 检查人脸识别复选框状态
            if self.isFaceTrackerEnabled:  # 人脸识别要在人脸追踪的基础上启动
                self.isFaceRecognizerEnabled = True
                coreUI.statusBar().showMessage('人脸识别：开启')  # 左下角状态提示栏
            else:
                CoreUI.logQueue.put('Error：操作失败，请先开启人脸跟踪')
                coreUI.faceRecognizerCheckBox.setCheckState(Qt.Unchecked)
                coreUI.faceRecognizerCheckBox.setChecked(False)
        else:
            self.isFaceRecognizerEnabled = False
            coreUI.statusBar().showMessage('人脸识别：关闭')

    # 是否开启报警系统
    def enablePanalarm(self, coreUI):
        if coreUI.panalarmCheckBox.isChecked():  # 检查人脸识别复选框状态
            if self.isFaceRecognizerEnabled:  # 人脸识别要在人脸追踪的基础上启动
                self.isPanalarmEnabled = True
                coreUI.statusBar().showMessage('签到系统：开启')  # 左下角状态提示栏
            else:
                CoreUI.logQueue.put('Error：操作失败，请先开启人脸识别')
                coreUI.panalarmCheckBox.setCheckState(Qt.Unchecked)
                coreUI.panalarmCheckBox.setChecked(False)
        else:
            self.panalarmCheckBox = False
            coreUI.statusBar().showMessage('签到系统：关闭')

    # 启用haar+LBPH识别算法
    def enable_haar_faceCascade(self, coreUI):
        if coreUI.haar_faceTrackerCheckBox.isChecked():  # 检查haar人脸追踪复选框状态
            self.is_haar_faceCascade = True
            coreUI.statusBar().showMessage('haar人脸跟踪：开启')  # 左下角状态提示栏
        else:
            self.is_haar_faceCascade = False
            coreUI.statusBar().showMessage('haar人脸跟踪：关闭')

    # 是否开启调试模式
    def enableDebug(self, coreUI):
        if coreUI.debugCheckBox.isChecked():
            self.isDebugMode = True
            coreUI.statusBar().showMessage('调试模式：开启')
        else:
            self.isDebugMode = False
            coreUI.statusBar().showMessage('调试模式：关闭')

    # 设置置信度阈值
    def setConfidenceThreshold(self, coreUI):
        if self.isDebugMode:
            self.confidenceThreshold = coreUI.confidenceThresholdSlider.value()  # 滑动设置置信度预支
            coreUI.statusBar().showMessage('置信度阈值：{}'.format(self.confidenceThreshold))

    # 设置自动报警阈值
    def setAutoAlarmThreshold(self, coreUI):
        if self.isDebugMode:
            self.autoAlarmThreshold = coreUI.autoAlarmThresholdSlider.value()  # 滑动设置报警阈值
            coreUI.statusBar().showMessage('自动报警阈值：{}'.format(self.autoAlarmThreshold))

    # 直方图均衡化
    def enableEqualizeHist(self, coreUI):
        if coreUI.equalizeHistCheckBox.isChecked():
            self.isEqualizeHistEnabled = True
            coreUI.statusBar().showMessage('直方图均衡化：开启')
        else:
            self.isEqualizeHistEnabled = False
            coreUI.statusBar().showMessage('直方图均衡化：关闭')

    # dlib人脸检测
    def find_faces_by_dlib(self, img):
        # 执行直方图均衡化
        if self.isEqualizeHistEnabled:
            img = cv2.equalizeHist(img)
        face_rects = dlib_detector(img, 0)  # 0表示检测次数，次数越多越准确，也约耗时

        return face_rects

    # haar人脸检测
    def find_faces_by_haar(self, gray):
        # 执行直方图均衡化
        if self.isEqualizeHistEnabled:
            gray = cv2.equalizeHist(gray)
        # 分类器进行人脸侦测,返回结果face是一个list保存矩形x,y,h,w
        faces = haar_faceCascade.detectMultiScale(gray, 1.3, 7, minSize=(80, 80))
        # 1.image为输入的灰度图像
        # 2.objects为得到被检测物体的矩形框向量组
        # 3.scaleFactor为每一个图像尺度中的尺度参数，默认值为1.1。scale_factor参数可以决定两个不同大小的窗口扫描之间有多大的跳跃，
        # 这个参数设置的大，则意味着计算会变快，但如果窗口错过了某个大小的人脸，则可能丢失物体。
        # 4.minNeighbors参数为每一个级联矩形应该保留的邻近个数，默认为3。
        # minNeighbors控制着误检测，默认值为3表明至少有3次重叠检测，我们才认为人脸确实存。
        # 6.cvSize()指示寻找人脸的最小区域。设置这个参数过大，会以丢失小物体为代价减少计算量。
        return faces

    # 删除低质量目标追踪器
    @staticmethod
    def del_low_quality_face_tracker(faceTrackers, realTimeFrame):
        fidsToDelete = []

        # 更新人脸追踪器，并删除低质量人脸
        for fid in faceTrackers.keys():
            # 实时跟踪下一帧
            trackingQuality = faceTrackers[fid].update(realTimeFrame)
            # 如果跟踪质量过低，删除该人脸跟踪器
            if trackingQuality < 7:
                fidsToDelete.append(fid)

        # 删除跟踪质量过低的人脸跟踪器，对多目标人脸追踪器更新。实时删除和增加
        for fid in fidsToDelete:
            faceTrackers.pop(fid, None)

    # 计算特征点欧氏距离
    @staticmethod
    def cal_euclideean_dis(feature_A, feature_B):
        feature_A = numpy.array(feature_A)
        feature_B = numpy.array(feature_B)
        dist = numpy.linalg.norm(feature_A - feature_B)
        return dist

    # 读取人脸特征数据
    @staticmethod
    def read_dlib_features_csv(reader):
        all_stu_features = []
        for row in range(0, reader.shape[0], 2):
            one_stu_features = []
            for col in range(len(reader.iloc[row + 1])):
                one_stu_features.append(reader.iloc[row + 1][col])
            stu_features = {'face_id': int(reader.iloc[row][0]), 'features': one_stu_features}
            all_stu_features.append(stu_features)
        return all_stu_features

    # 计算最佳匹配
    def cal_best_match(self, features_in_cap, all_stu_features):
        best_match_face_id = None
        min_dist = 1
        for item in all_stu_features:
            face_id, features = item.get('face_id', 0), item.get('features', [])
            dist = self.cal_euclideean_dis(features_in_cap, features)
            if dist < min_dist:
                best_match_face_id = face_id
                min_dist = dist
        return best_match_face_id, min_dist

    # OpenCV线程运行
    def run(self):
        # 遇到的坑：因为FaceProcess在初始化的时候才认为准备running，而FaceProcess不running就不会有处理过的帧进入队列
        # 也就不会更新镜头信息帧到主界面，因此必须在打开摄像头时认为FaceProcess启动，改变stop时False状态
        self.isRunning = True
        # 帧数、人脸ID初始化
        frameCounter = 0
        currentFaceID = 0

        # 人脸跟踪器字典初始化
        faceTrackers = dict()
        all_stu_features = []

        isTrainingDataLoaded = False  # 预加载训练数据标记，检查一次过后即可不检查
        isDbConnected = False  # 预连接数据库标记，连接一次后即可只检查标记

        while self.isRunning and CoreUI.cap.isOpened():
            ret, frame = CoreUI.cap.read()  # 从摄像头捕获帧

            # 预加载识别数据
            if not isTrainingDataLoaded and os.path.isfile(CoreUI.trainingData):  # 训练数据
                recognizer = cv2.face.LBPHFaceRecognizer_create()  # LBPH人脸识别对象
                recognizer.read(CoreUI.trainingData)  # 读取训练数据
                if os.path.exists(CoreUI.dlib_features_data):
                    csv_reader = pd.read_csv(CoreUI.dlib_features_data, header=None)
                    all_stu_features = self.read_dlib_features_csv(csv_reader)

                isTrainingDataLoaded = True

            if not isDbConnected:  # 学生信息数据库
                conn, cursor = connect_to_sql()
                isDbConnected = True

            captureData = {}  # 单帧识别结果
            realTimeFrame = frame.copy()  # copy原始帧的识别帧
            alarmSignal = {}  # 报警信号

            # haar级联分类器+LBPH局部二值模式识别方法
            if self.is_haar_faceCascade:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # 灰度图，改变颜色空间，实际上就是BGR三色2(to) 灰度GRAY
                faces = self.find_faces_by_haar(frame)  # 分类器获取人脸

                # 为什么要用haar+dlib多目标追踪，因为haar每次只能识别一张人脸，多目标追踪器可以记录下每次新增的人脸，那么haar负责检测人脸，多目标追踪负责记录和同时追踪多个人脸

                # 人脸跟踪
                # Reference：https://github.com/gdiepen/face-recognition
                if self.isFaceTrackerEnabled:
                    know_faces = set()

                    # 删除质量较低的跟踪器
                    self.del_low_quality_face_tracker(faceTrackers, realTimeFrame)

                    # 遍历所有侦测到的人脸坐标
                    for (_x, _y, _w, _h) in faces:

                        # 微笑检测
                        smiles_y = (_y + _h + _y) // 2
                        smiles = haar_smile_cascade.detectMultiScale(gray[smiles_y:_y + _h, _x:_x + _w], 1.3, 10,
                                                                     minSize=(10, 10))
                        for (x, y, w, h) in smiles:
                            cv2.rectangle(realTimeFrame, (_x + x, smiles_y + y), (_x + x + w, smiles_y + y + h),
                                          (200, 50, 0), 1)
                            break

                        # 眼部检测
                        eyes = haar_eyes_cascade.detectMultiScale(gray[_y:smiles_y, _x:_x + _w], 1.3, 10,
                                                                  minSize=(40, 40))
                        for (x, y, w, h) in eyes:
                            cv2.rectangle(realTimeFrame, (_x + x, _y + y), (_x + x + w, _y + y + h), (150, 255, 30), 1)

                        isKnown = False

                        # 人脸识别
                        if self.isFaceRecognizerEnabled:
                            # 蓝色识别框（RGB三通道色参数其实顺序是BGR）
                            cv2.rectangle(realTimeFrame, (_x, _y), (_x + _w, _y + _h), (232, 138, 30), 2)
                            # 预测函数，识别后返回face ID和差异程度，差异程度越小越相似
                            face_id, confidence = recognizer.predict(gray[_y:_y + _h, _x:_x + _w])
                            logging.debug('face_id：{}，confidence：{}'.format(face_id, confidence))

                            if self.isDebugMode:  # 调试模式输出每帧识别信息
                                CoreUI.logQueue.put('Debug -> face_id：{}，confidence：{}'.format(face_id, confidence))

                            # 从数据库中获取识别人脸的身份信息
                            try:
                                cursor.execute("SELECT * FROM users WHERE face_id=%s", (face_id,))
                                result = cursor.fetchall()
                                if result:
                                    stu_id = str(result[0][0])  # 学号
                                    zh_name = result[0][2]  # 中文名
                                    en_name = result[0][3]  # 英文名
                                else:
                                    raise Exception
                            except Exception as e:
                                logging.error('读取数据库异常，系统无法获取Face ID为{}的身份信息'.format(face_id))
                                CoreUI.logQueue.put('Error：读取数据库异常，系统无法获取Face ID为{}的身份信息'.format(face_id))
                                stu_id = ''
                                zh_name = ''
                                en_name = ''

                            # 若置信度评分小于置信度阈值，认为是可靠识别
                            if confidence < self.confidenceThreshold:
                                isKnown = True
                                if self.isPanalarmEnabled:  # 签到系统启动状态下执行
                                    stu_statu = self.attendance_list.get(stu_id, 0)
                                    if stu_statu > 9:
                                        realTimeFrame = cv2ImgAddText(realTimeFrame, '已识别', _x + _w - 45, _y - 10,
                                                                      (0, 97, 255))  # 帧签到状态标记
                                    elif stu_statu <= 8:
                                        # 连续帧识别判断，避免误识
                                        self.attendance_list[stu_id] = stu_statu + 1
                                    else:
                                        attendance_time = datetime.now()
                                        self.attendance_list[stu_id] = stu_statu + 1
                                        alarmSignal = {
                                            'id': stu_id,
                                            'name': zh_name,
                                            'time': attendance_time,
                                            'img': realTimeFrame
                                        }
                                        CoreUI.attendance_queue.put(alarmSignal)  # 签到队列插入该信号
                                        logging.info('系统发出了新的签到信号')
                                # 置信度标签
                                cv2.putText(realTimeFrame, str(round(100 - confidence, 3)), (_x - 5, _y + _h + 18),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                            (0, 255, 255), 1)
                                # 蓝色英文名标签
                                cv2.putText(realTimeFrame, en_name, (_x - 5, _y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1,
                                            (0, 97, 255), 2)
                                # 蓝色中文名标签
                                realTimeFrame = cv2ImgAddText(realTimeFrame, zh_name, _x - 5, _y - 10, (0, 97, 255))

                                know_faces.add(stu_id)
                                if self.isDebugMode:  # 调试模式输出每帧识别信息
                                    print(know_faces)
                                    print(self.attendance_list)
                            else:
                                cv2.putText(realTimeFrame, str(round(100 - confidence, 3)), (_x - 5, _y + _h + 18),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                            (0, 50, 255), 1)
                                # 若置信度评分大于置信度阈值，该人脸可能是陌生人
                                cv2.putText(realTimeFrame, 'unknown', (_x - 5, _y - 10), cv2.FONT_HERSHEY_SIMPLEX, 1,
                                            (0, 0, 255), 2)
                                # 若置信度评分超出自动报警阈值，触发报警信号
                                if confidence > self.autoAlarmThreshold:
                                    # 报警系统是否开启
                                    if self.isPanalarmEnabled:  # 记录报警时间戳和当前帧
                                        alarmSignal['timestamp'] = datetime.now().strftime('%Y%m%d%H%M%S')
                                        alarmSignal['img'] = realTimeFrame
                                        CoreUI.alarmQueue.put(alarmSignal)  # 报警队列插入该信号
                                        logging.info('系统发出了未知人脸信号')

                        # 帧数计数器
                        frameCounter += 1

                        # 每读取10帧，更新检测跟踪器的新增人脸
                        if frameCounter % 10 == 0:
                            frameCounter = 0  # 防止爆int
                            # 这里必须转换成int类型，因为OpenCV人脸检测返回的是numpy.int32类型，
                            # 而dlib人脸跟踪器要求的是int类型
                            x, y, w, h = int(_x), int(_y), int(_w), int(_h)

                            # 计算中心点
                            x_bar = x + 0.5 * w
                            y_bar = y + 0.5 * h

                            # matchedFid表征当前检测到的人脸是否已被跟踪，未赋值则
                            matchedFid = None

                            # 将OpenCV中haar分类器获取的人脸位置与dlib人脸追踪器的位置做对比
                            # 上方坐标表示分类器检测结果，下方坐标表示遍历多目标追踪器检查有没有坐标上重合的脸，如果有，matchFid被赋值，说明该脸已追踪
                            # 如果没有，说明该分类器捕获的脸没有被追踪，那么多目标追踪器需要分配新的fid和追踪器实例

                            # 遍历人脸追踪器的face_id
                            for fid in faceTrackers.keys():
                                # 获取人脸跟踪器的位置
                                # tracked_position 是 dlib.drectangle 类型，用来表征图像的矩形区域，坐标是浮点数
                                tracked_position = faceTrackers[fid].get_position()
                                # 浮点数取整
                                t_x = int(tracked_position.left())
                                t_y = int(tracked_position.top())
                                t_w = int(tracked_position.width())
                                t_h = int(tracked_position.height())

                                # 计算人脸跟踪器的中心点
                                t_x_bar = t_x + 0.5 * t_w
                                t_y_bar = t_y + 0.5 * t_h

                                # 如果当前检测到的人脸中心点落在人脸跟踪器内，且人脸跟踪器的中心点也落在当前检测到的人脸内
                                # 说明当前人脸已被跟踪
                                if ((t_x <= x_bar <= (t_x + t_w)) and (t_y <= y_bar <= (t_y + t_h)) and
                                        (x <= t_x_bar <= (x + w)) and (y <= t_y_bar <= (y + h))):
                                    matchedFid = fid

                            # 如果当前检测到的人脸是陌生人脸且未被跟踪
                            if not isKnown and matchedFid is None:
                                # 创建一个追踪器
                                tracker = dlib.correlation_tracker()  # 多目标追踪器
                                # 设置图片中被追踪物体的范围，也就是一个矩形框
                                tracker.start_track(realTimeFrame, dlib.rectangle(x - 5, y - 10, x + w + 5, y + h + 10))
                                # 将该人脸跟踪器分配给当前检测到的人脸
                                faceTrackers[currentFaceID] = tracker
                                # 人脸ID自增
                                currentFaceID += 1

                    # 遍历人脸跟踪器，输出追踪人脸的位置
                    for fid in faceTrackers.keys():
                        tracked_position = faceTrackers[fid].get_position()

                        t_x = int(tracked_position.left())
                        t_y = int(tracked_position.top())
                        t_w = int(tracked_position.width())
                        t_h = int(tracked_position.height())

                        # 在跟踪帧中绘制方框圈出人脸，红框
                        cv2.rectangle(realTimeFrame, (t_x, t_y), (t_x + t_w, t_y + t_h), (0, 0, 255), 2)
                        # 图像/添加的文字/左上角坐标/字体/字体大小/颜色/字体粗细
                        cv2.putText(realTimeFrame, 'tracking...', (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255),
                                    1)
                    del_list = []
                    for stu_id, value in self.attendance_list.items():
                        if stu_id not in know_faces and value <= 8:
                            del_list.append(stu_id)
                    for stu_id in del_list:
                        self.attendance_list.pop(stu_id, 0)

            else:
                # dlib人脸关键点识别,绿框
                face_rects = self.find_faces_by_dlib(frame)
                # print(face_rects, scores, idx)  # rectangles[[(281, 209) (496, 424)]] [0.07766452427949444] [4]

                if self.isFaceTrackerEnabled:
                    know_faces = set()
                    # 删除质量较低的跟踪器
                    # self.del_low_quality_face_tracker(faceTrackers, realTimeFrame)

                    # 遍历所有侦测到的人脸坐标
                    for rect in face_rects:

                        isKnown = False

                        left = rect.left()
                        top = rect.top()
                        right = rect.right()
                        bottom = rect.bottom()

                        # 绘制出侦测人臉的矩形范围,绿框
                        cv2.rectangle(realTimeFrame, (left - 5, top - 5), (right + 5, bottom + 5), (0, 255, 0), 4,
                                      cv2.LINE_AA)

                        # 给68特征点识别取得一个转换顏色的frame
                        landmarks_frame = cv2.cvtColor(realTimeFrame, cv2.COLOR_BGR2RGB)

                        # 找出特征点位置, 参数为转换色彩空间后的帧图像以及脸部位置
                        shape = predictor_5(landmarks_frame, rect)

                        # 绘制5个特征点
                        for i in range(5):
                            cv2.circle(realTimeFrame, (shape.part(i).x, shape.part(i).y), 1, (0, 0, 255), 2)
                            cv2.putText(realTimeFrame, str(i), (shape.part(i).x, shape.part(i).y),
                                        cv2.FONT_HERSHEY_COMPLEX,
                                        0.5,
                                        (255, 0, 0), 1)

                        # 图像/添加的文字/左上角坐标/字体/字体大小/颜色/字体粗细
                        cv2.putText(realTimeFrame, 'tracking...', (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0),
                                    1)

                        # 人脸识别
                        if self.isFaceRecognizerEnabled:
                            # 蓝色识别框（RGB三通道色参数其实顺序是BGR）
                            cv2.rectangle(realTimeFrame, (left, top), (right, bottom), (232, 138, 30), 2)
                            # 预测函数，识别后返回face ID和差异程度，差异程度越小越相似
                            face_features = facerec.compute_face_descriptor(frame, shape)
                            face_id, confidence = self.cal_best_match(face_features, all_stu_features)
                            logging.debug('face_id：{}，confidence：{}'.format(face_id, confidence))

                            if self.isDebugMode:  # 调试模式输出每帧识别信息
                                CoreUI.logQueue.put('Debug -> face_id：{}，confidence：{}'.format(face_id, confidence))

                            # 若置信度评分小于置信度阈值，认为是可靠识别
                            if confidence < 0.45:

                                # 从数据库中获取识别人脸的身份信息
                                try:
                                    cursor.execute("SELECT * FROM users WHERE face_id=%s", (face_id,))
                                    result = cursor.fetchall()
                                    if result:
                                        stu_id = str(result[0][0])  # 学号
                                        zh_name = result[0][2]  # 中文名
                                        en_name = result[0][3]  # 英文名
                                    else:
                                        raise Exception
                                except Exception as e:
                                    logging.error('读取数据库异常，系统无法获取Face ID为{}的身份信息'.format(face_id))
                                    CoreUI.logQueue.put('Error：读取数据库异常，系统无法获取Face ID为{}的身份信息'.format(face_id))
                                    stu_id = ''
                                    zh_name = ''
                                    en_name = ''

                                isKnown = True
                                if self.isPanalarmEnabled:  # 签到系统启动状态下执行
                                    stu_statu = self.attendance_list.get(stu_id, 0)
                                    if stu_statu > 7:
                                        realTimeFrame = cv2ImgAddText(realTimeFrame, '已识别', right - 45, top - 10,
                                                                      (0, 97, 255))  # 帧签到状态标记
                                    elif stu_statu <= 6:
                                        # 连续帧识别判断，避免误识
                                        self.attendance_list[stu_id] = stu_statu + 1
                                    else:
                                        attendance_time = datetime.now()
                                        self.attendance_list[stu_id] = stu_statu + 1
                                        alarmSignal = {
                                            'id': stu_id,
                                            'name': zh_name,
                                            'time': attendance_time,
                                            'img': realTimeFrame,
                                        }
                                        CoreUI.attendance_queue.put(alarmSignal)  # 签到队列插入该信号
                                        logging.info('系统发出了新的签到信号')
                                # 置信度标签
                                cv2.putText(realTimeFrame, str(round((1 - confidence) * 100, 4)),
                                            (left - 5, bottom + 18),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                            (0, 255, 255), 1)
                                # 蓝色英文名标签
                                cv2.putText(realTimeFrame, en_name, (left - 5, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 1,
                                            (0, 97, 255), 2)
                                # 蓝色中文名标签
                                realTimeFrame = cv2ImgAddText(realTimeFrame, zh_name, left - 5, top - 10, (0, 97, 255))

                                know_faces.add(stu_id)
                                if self.isDebugMode:  # 调试模式输出每帧识别信息
                                    print(know_faces)
                                    print(self.attendance_list)
                            else:
                                cv2.putText(realTimeFrame, str(round((1 - confidence) * 100, 3)),
                                            (left - 5, bottom + 18),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                            (0, 50, 255), 1)
                                # 若置信度评分大于置信度阈值，该人脸可能是陌生人
                                cv2.putText(realTimeFrame, 'unknown', (left - 5, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 1,
                                            (0, 0, 255), 2)
                                # 若置信度评分超出自动报警阈值，触发报警信号
                                # if confidence > 0.8:
                                #     # 报警系统是否开启
                                #     if self.isPanalarmEnabled:  # 记录报警时间戳和当前帧
                                #         alarmSignal['timestamp'] = datetime.now().strftime('%Y%m%d%H%M%S')
                                #         alarmSignal['img'] = realTimeFrame
                                #         CoreUI.alarmQueue.put(alarmSignal)  # 报警队列插入该信号
                                #         logging.info('系统发出了未知人脸信号')

                        # 帧数计数器
                        frameCounter += 1

                        # 每读取10帧，检测跟踪器的人脸是否还在当前画面内
                        # if frameCounter % 10 == 0:
                        #     frameCounter = 0  # 防止爆int
                        #     # 这里必须转换成int类型，因为OpenCV人脸检测返回的是numpy.int32类型，
                        #     # 而dlib人脸跟踪器要求的是int类型
                        #
                        #     # 计算中心点
                        #     x_bar = (left + right) * 0.5
                        #     y_bar = (top + bottom) * 0.5
                        #
                        #     # matchedFid表征当前检测到的人脸是否已被跟踪，未赋值则
                        #     matchedFid = None
                        #
                        #     # 将OpenCV中haar分类器获取的人脸位置与dlib人脸追踪器的位置做对比
                        #     # 上方坐标表示分类器检测结果，下方坐标表示遍历多目标追踪器检查有没有坐标上重合的脸，如果有，matchFid被赋值，说明该脸已追踪
                        #     # 如果没有，说明该分类器捕获的脸没有被追踪，那么多目标追踪器需要分配新的fid和追踪器实例
                        #
                        #     # 遍历人脸追踪器的face_id
                        #     for fid in faceTrackers.keys():
                        #         # 获取人脸跟踪器的位置
                        #         # tracked_position 是 dlib.drectangle 类型，用来表征图像的矩形区域，坐标是浮点数
                        #         tracked_position = faceTrackers[fid].get_position()
                        #         # 浮点数取整
                        #         t_x = int(tracked_position.left())
                        #         t_y = int(tracked_position.top())
                        #         t_w = int(tracked_position.width())
                        #         t_h = int(tracked_position.height())
                        #
                        #         # 计算人脸跟踪器的中心点
                        #         t_x_bar = t_x + 0.5 * t_w
                        #         t_y_bar = t_y + 0.5 * t_h
                        #
                        #         # 如果当前检测到的人脸中心点落在人脸跟踪器内，且人脸跟踪器的中心点也落在当前检测到的人脸内
                        #         # 说明当前人脸已被跟踪
                        #         if ((t_x <= x_bar <= (t_x + t_w)) and (t_y <= y_bar <= (t_y + t_h)) and
                        #                 (left <= t_x_bar <= right) and (top <= t_y_bar <= bottom)):
                        #             matchedFid = fid
                        #
                        #     # 如果当前检测到的人脸是陌生人脸且未被跟踪
                        #     if not isKnown and matchedFid is None:
                        #         # 创建一个追踪器
                        #         tracker = dlib.correlation_tracker()  # 多目标追踪器
                        #         # 设置图片中被追踪物体的范围，也就是一个矩形框
                        #         tracker.start_track(realTimeFrame, dlib.rectangle(left - 5, top - 10, right + 5, bottom + 10))
                        #         # 将该人脸跟踪器分配给当前检测到的人脸
                        #         faceTrackers[currentFaceID] = tracker
                        #         # 人脸ID自增
                        #         currentFaceID += 1

                    # # 遍历人脸跟踪器，标出追踪人脸的位置
                    # for fid in faceTrackers.keys():
                    #     tracked_position = faceTrackers[fid].get_position()
                    #
                    #     t_x = int(tracked_position.left())
                    #     t_y = int(tracked_position.top())
                    #     t_w = int(tracked_position.width())
                    #     t_h = int(tracked_position.height())
                    #
                    #     # 在跟踪帧中绘制方框圈出人脸，红框
                    #     cv2.rectangle(realTimeFrame, (t_x, t_y), (t_x + t_w, t_y + t_h), (0, 0, 255), 2)
                    #     # 图像/添加的文字/左上角坐标/字体/字体大小/颜色/字体粗细
                    #     cv2.putText(realTimeFrame, 'tracking...', (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255),
                    #                 1)
                    del_list = []
                    for stu_id, value in self.attendance_list.items():
                        if stu_id not in know_faces and value <= 6:
                            del_list.append(stu_id)
                    for stu_id in del_list:
                        self.attendance_list.pop(stu_id, 0)
            captureData['originFrame'] = frame
            captureData['realTimeFrame'] = realTimeFrame
            CoreUI.captureQueue.put(captureData)

    # 停止OpenCV线程
    def stop(self):
        self.isRunning = False
        self.quit()
        self.wait()


class CreatClassDialog(QDialog):

    def __init__(self):
        super(CreatClassDialog, self).__init__()
        loadUi('./ui/CreateClass.ui', self)  # 读取UI布局
        self.setWindowIcon(QIcon('./icons/icon.png'))

        # 设置tableWidget只读，不允许修改
        self.AllStuTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.AddStuTable.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # 表格双色√
        self.AllStuTable.setAlternatingRowColors(True)
        self.AddStuTable.setAlternatingRowColors(True)

        self.AddpushButton.clicked.connect(self.add_stu_to_table)
        self.DelpushButton.clicked.connect(self.del_stu_from_table)

        self.add_set = set()

        try:
            conn, cursor = connect_to_sql()  # 连接数据库

            if not DataRecordUI.table_exists(cursor, CoreUI.database):
                raise FileNotFoundError

            cursor.execute('SELECT stu_id, cn_name, major, grade, class FROM users')
            conn.commit()
            stu_data = cursor.fetchall()
            # print(stu_data)
            self.print_to_table(stu_data)  # 输出到表格界面
        except FileNotFoundError:
            logging.error('系统找不到数据库表{}'.format(CoreUI.database))
        except Exception as e:
            print(e)
            logging.error('读取数据库异常，无法完成数据库查询')
        else:
            cursor.close()
            conn.close()

    def print_to_table(self, stu_data):
        while self.AllStuTable.rowCount() > 0:
            self.AllStuTable.removeRow(0)
        for row_index, row_data in enumerate(stu_data):
            self.AllStuTable.insertRow(row_index)  # 插入行
            for col_index, col_data in enumerate(row_data):  # 插入列
                self.AllStuTable.setItem(row_index, col_index, QTableWidgetItem(str(col_data)))  # 设置单元格文本

    # 增加学生
    def add_stu_to_table(self):
        select_items = self.AllStuTable.selectedItems()  # 选中的所有单元格
        column_count = self.AllStuTable.columnCount()  # 表格列数
        ""

        stu_count = len(select_items) // column_count  # 选中行数
        for index in range(stu_count):
            one_stu = select_items[index * column_count: (index + 1) * column_count]
            if one_stu[0].text() in self.add_set:  # 过滤重复学号
                continue
            row_count = self.AddStuTable.rowCount()  # 总行数
            self.AddStuTable.setRowCount(row_count + 1)  # 增加总行数
            self.add_set.add(one_stu[0].text())  # 增加学生在已选择set
            for col in range(column_count):
                if self.AddStuTable.item(row_count, col) is None:
                    self.AddStuTable.setItem(row_count, col, QTableWidgetItem(one_stu[col].text()))
        # print(self.add_set)

    # 删除学生
    def del_stu_from_table(self):
        select_items = self.AddStuTable.selectedItems()[::self.AddStuTable.columnCount()]  # 获取所有选中删除的学号
        del_list = []
        for item in select_items:
            # print(item.text())
            self.add_set.remove(item.text())  # 从已选set中删除
            del_list.append(item.row())
        del_list.sort()  # 为了实现多选删除，使用偏移量保证删除下标的正确性
        for index, item in enumerate(del_list):
            self.AddStuTable.removeRow(item - index)
        # print(self.add_set)


if __name__ == '__main__':
    logging.config.fileConfig('./config/logging.cfg')
    app = QApplication(sys.argv)
    window = CoreUI()
    window.show()
    sys.exit(app.exec())

# 出勤率分析折线图，选择课程签到表创建折线图
