#!/usr/bin/env python3
# Author: kuronekonano <god772525182@gmail.com>

import cv2
import numpy as np
import pymysql

from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtGui import QIcon, QTextCursor
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox, QTableWidgetItem, QAbstractItemView, QProgressBar, QDialog
from PyQt5.uic import loadUi

import logging
import logging.config
import os
import shutil
import sqlite3
import sys
import threading
import multiprocessing

from datetime import datetime
from dataRecord import DataRecordUI

# 自定义数据库记录不存在异常
class RecordNotFound(Exception):
    pass


class DataManageUI(QWidget):
    logQueue = multiprocessing.Queue()  # 日志队列
    receiveLogSignal = pyqtSignal(str)  # 日志信号

    def __init__(self):
        super(DataManageUI, self).__init__()
        loadUi('./ui/DataManage.ui', self)
        self.setWindowIcon(QIcon('./icons/icon.png'))
        self.setFixedSize(1451, 878)

        # 设置tableWidget只读，不允许修改
        self.tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # 数据库
        self.database = 'users'
        self.datasets = './datasets'
        self.isDbReady = False
        self.initDbButton.clicked.connect(self.initDb)

        # 用户管理
        self.queryUserButton.clicked.connect(self.queryUser)
        self.deleteUserButton.clicked.connect(self.deleteUser)

        # 直方图均衡化
        self.isEqualizeHistEnabled = False
        self.equalizeHistCheckBox.stateChanged.connect(
            lambda: self.enableEqualizeHist(self.equalizeHistCheckBox))

        # 训练人脸数据
        self.trainButton.clicked.connect(self.train)

        # 系统日志
        self.receiveLogSignal.connect(lambda log: self.logOutput(log))
        self.logOutputThread = threading.Thread(target=self.receiveLog, daemon=True)
        self.logOutputThread.start()

    # 是否执行直方图均衡化
    def enableEqualizeHist(self, equalizeHistCheckBox):
        if equalizeHistCheckBox.isChecked():
            self.isEqualizeHistEnabled = True
        else:
            self.isEqualizeHistEnabled = False

    # 初始化/刷新数据库
    def initDb(self):
        # 刷新前清空tableWidget
        while self.tableWidget.rowCount() > 0:
            self.tableWidget.removeRow(0)
        try:
            conn = pymysql.connect(host='localhost',
                                   user='root',
                                   password='970922',
                                   db='mytest',
                                   port=3306,
                                   charset='utf8')
            cursor = conn.cursor()

            if not DataRecordUI.table_exists(cursor, self.database):
                raise FileNotFoundError

            cursor.execute('SELECT * FROM users')
            conn.commit()
            stu_data = cursor.fetchall()
            # print(stu_data)
            for row_index, row_data in enumerate(stu_data):
                self.tableWidget.insertRow(row_index)  # 插入行
                for col_index, col_data in enumerate(row_data):  # 插入列
                    self.tableWidget.setItem(row_index, col_index, QTableWidgetItem(str(col_data)))
            cursor.execute('SELECT Count(*) FROM users')  # 学生计数
            result = cursor.fetchone()
            dbUserCount = result[0]
        except FileNotFoundError:
            logging.error('系统找不到数据库表{}'.format(self.database))
            self.isDbReady = False
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：未发现数据库，你可能未进行人脸采集')
        except Exception:
            logging.error('读取数据库异常，无法完成数据库初始化')
            self.isDbReady = False
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：读取数据库异常，初始化/刷新数据库失败')
        else:
            cursor.close()
            conn.close()

            self.dbUserCountLcdNum.display(dbUserCount)
            if not self.isDbReady:
                self.isDbReady = True
                self.logQueue.put('Success：数据库初始化完成，发现用户数：{}'.format(dbUserCount))
                self.initDbButton.setText('刷新数据库')
                self.initDbButton.setIcon(QIcon('./icons/success.png'))
                self.trainButton.setToolTip('')
                self.trainButton.setEnabled(True)
                self.queryUserButton.setToolTip('')
                self.queryUserButton.setEnabled(True)
            else:
                self.logQueue.put('Success：刷新数据库成功，发现用户数：{}'.format(dbUserCount))

    # 查询用户
    def queryUser(self):
        stu_id = self.queryUserLineEdit.text().strip()
        conn = pymysql.connect(host='localhost',
                               user='root',
                               password='970922',
                               db='mytest',
                               port=3306,
                               charset='utf8')
        cursor = conn.cursor()
        # conn = sqlite3.connect(self.database)
        # cursor = conn.cursor()

        try:
            cursor.execute('SELECT * FROM users WHERE stu_id=%s', (stu_id,))
            ret = cursor.fetchall()
            if not ret:
                raise RecordNotFound
            face_id = ret[0][1]
            cn_name = ret[0][2]
        except RecordNotFound:
            self.queryUserButton.setIcon(QIcon('./icons/error.png'))
            self.queryResultLabel.setText('<font color=red>Error：此用户不存在</font>')
        except Exception as e:
            logging.error('读取数据库异常，无法查询到{}的用户信息'.format(stu_id))
            self.queryResultLabel.clear()
            self.queryUserButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：读取数据库异常，查询失败')
        else:
            self.queryResultLabel.clear()
            self.queryUserButton.setIcon(QIcon('./icons/success.png'))
            self.stuIDLineEdit.setText(stu_id)
            self.cnNameLineEdit.setText(cn_name)
            self.faceIDLineEdit.setText(str(face_id))
            self.deleteUserButton.setEnabled(True)
        finally:
            cursor.close()
            conn.close()

    # 删除用户
    def deleteUser(self):
        text = '从数据库中删除该用户，同时删除相应人脸数据，<font color=red>该操作不可逆！</font>'
        informativeText = '<b>是否继续？</b>'
        ret = DataManageUI.callDialog(QMessageBox.Warning, text, informativeText, QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)

        if ret == QMessageBox.Yes:
            stu_id = self.stuIDLineEdit.text()
            conn = pymysql.connect(host='localhost',
                                   user='root',
                                   password='970922',
                                   db='mytest',
                                   port=3306,
                                   charset='utf8')
            cursor = conn.cursor()
            # conn = sqlite3.connect(self.database)
            # cursor = conn.cursor()

            try:
                cursor.execute('DELETE FROM users WHERE stu_id=%s', (stu_id,))
            except Exception as e:
                cursor.close()
                logging.error('无法从数据库中删除{}'.format(stu_id))
                self.deleteUserButton.setIcon(QIcon('./icons/error.png'))
                self.logQueue.put('Error：读写数据库异常，删除失败')
            else:
                cursor.close()
                conn.commit()
                if os.path.exists('{}/stu_{}'.format(self.datasets, stu_id)):
                    try:
                        shutil.rmtree('{}/stu_{}'.format(self.datasets, stu_id))
                    except Exception as e:
                        logging.error('系统无法删除删除{}/stu_{}'.format(self.datasets, stu_id))
                        self.logQueue.put('Error：删除人脸数据失败，请手动删除{}/stu_{}目录'.format(self.datasets, stu_id))

                text = '你已成功删除学号为 <font color=blue>{}</font> 的用户记录。'.format(stu_id)
                informativeText = '<b>请在右侧菜单重新训练人脸数据。</b>'
                DataManageUI.callDialog(QMessageBox.Information, text, informativeText, QMessageBox.Ok)

                self.stuIDLineEdit.clear()
                self.cnNameLineEdit.clear()
                self.faceIDLineEdit.clear()
                self.initDb()
                self.deleteUserButton.setIcon(QIcon('./icons/success.png'))
                self.deleteUserButton.setEnabled(False)
                self.queryUserButton.setIcon(QIcon())
            finally:
                conn.close()

    # 检测人脸
    def detectFace(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)  # 灰度图
        if self.isEqualizeHistEnabled:  # 直方均衡化
            gray = cv2.equalizeHist(gray)
        face_cascade = cv2.CascadeClassifier('./haarcascades/haarcascade_frontalface_default.xml')  # 分类器
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5, minSize=(90, 90))  # 抠脸

        if len(faces) == 0:
            return None, None
        (x, y, w, h) = faces[0]
        return gray[y:y + w, x:x + h], faces[0]

    # 准备图片数据，参数为数据集路径
    def prepareTrainingData(self, data_folder_path):
        dirs = os.listdir(data_folder_path)  # 返回指定的文件夹包含的文件或文件夹的名字的列表
        faces = []
        labels = []

        face_id = 1

        conn = pymysql.connect(host='localhost',
                               user='root',
                               password='970922',
                               db='mytest',
                               port=3306,
                               charset='utf8')
        cursor = conn.cursor()
        # conn = sqlite3.connect(self.database)  # 连接数据库
        # cursor = conn.cursor()

        # 遍历人脸库
        for dir_name in dirs:
            if not dir_name.startswith('stu_'):  # 跳过不合法的图片集
                continue
            stu_id = dir_name.replace('stu_', '')  # 获取图片集对应的学号
            try:
                cursor.execute('SELECT * FROM users WHERE stu_id=%s', (stu_id,))  # 根据学号查询学生信息
                ret = cursor.fetchall()
                if not ret:
                    raise RecordNotFound  # 在try里raise错误类型，在except里再处理
                cursor.execute('UPDATE users SET face_id=%s WHERE stu_id=%s', (face_id, stu_id,))  # 对可以训练的人脸设置face_id
            except RecordNotFound:
                logging.warning('数据库中找不到学号为{}的用户记录'.format(stu_id))
                self.logQueue.put('发现学号为{}的人脸数据，但数据库中找不到相应记录，已忽略'.format(stu_id))
                continue
            subject_dir_path = data_folder_path + '/' + dir_name  # 子目录
            subject_images_names = os.listdir(subject_dir_path)  # 获取所有图片名
            for image_name in subject_images_names:
                if image_name.startswith('.'):  # 忽略隐藏文件
                    continue
                image_path = subject_dir_path + '/' + image_name
                image = cv2.imread(image_path)  # 读取图片
                face, rect = self.detectFace(image)  # 探测人脸，返回
                if face is not None:
                    faces.append(face)  # D到的脸放入list
                    labels.append(face_id)  # face_id放入标签，同一个人的脸同一个face_id
            face_id = face_id + 1

        cursor.close()
        conn.commit()
        conn.close()

        return faces, labels

    # 训练人脸数据
    # Reference：https://github.com/informramiz/opencv-face-recognition-python
    def train(self):
        try:
            if not os.path.isdir(self.datasets):
                raise FileNotFoundError

            text = '系统将开始训练人脸数据，界面会暂停响应一段时间，完成后会弹出提示。'
            informativeText = '<b>训练过程请勿进行其它操作，是否继续？</b>'
            ret = DataManageUI.callDialog(QMessageBox.Question, text, informativeText,
                                          QMessageBox.Yes | QMessageBox.No,
                                          QMessageBox.No)
            if ret == QMessageBox.Yes:
                face_recognizer = cv2.face.LBPHFaceRecognizer_create()
                if not os.path.exists('./recognizer'):
                    os.makedirs('./recognizer')
                faces, labels = self.prepareTrainingData(self.datasets)  # 准备图片数据
                face_recognizer.train(faces, np.array(labels))
                face_recognizer.save('./recognizer/trainingData.yml')
        except FileNotFoundError:
            logging.error('系统找不到人脸数据目录{}'.format(self.datasets))
            self.trainButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('未发现人脸数据目录{}，你可能未进行人脸采集'.format(self.datasets))
        except Exception as e:
            logging.error('遍历人脸库出现异常，训练人脸数据失败')
            self.trainButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：遍历人脸库出现异常，训练失败')
        else:
            text = '<font color=green><b>Success!</b></font> 系统已生成./recognizer/trainingData.yml'
            informativeText = '<b>人脸数据训练完成！</b>'
            DataManageUI.callDialog(QMessageBox.Information, text, informativeText, QMessageBox.Ok)
            self.trainButton.setIcon(QIcon('./icons/success.png'))
            self.logQueue.put('Success：人脸数据训练完成')
            self.initDb()

    # 系统日志服务常驻，接收并处理系统日志
    def receiveLog(self):
        while True:
            data = self.logQueue.get()
            if data:
                self.receiveLogSignal.emit(data)
            else:
                continue

    # LOG输出
    def logOutput(self, log):
        time = datetime.now().strftime('[%Y/%m/%d %H:%M:%S]')
        log = time + ' ' + log + '\n'

        self.logTextEdit.moveCursor(QTextCursor.End)
        self.logTextEdit.insertPlainText(log)
        self.logTextEdit.ensureCursorVisible()  # 自动滚屏

    # 系统对话框
    @staticmethod
    def callDialog(icon, text, informativeText, standardButtons, defaultButton=None):
        msg = QMessageBox()
        msg.setWindowIcon(QIcon('./icons/icon.png'))
        msg.setWindowTitle('OpenCV Face Recognition System - DataManage')
        msg.setIcon(icon)
        msg.setText(text)
        msg.setInformativeText(informativeText)
        msg.setStandardButtons(standardButtons)
        if defaultButton:
            msg.setDefaultButton(defaultButton)
        return msg.exec()


if __name__ == '__main__':
    logging.config.fileConfig('./config/logging.cfg')
    app = QApplication(sys.argv)
    window = DataManageUI()
    window.show()
    sys.exit(app.exec())
