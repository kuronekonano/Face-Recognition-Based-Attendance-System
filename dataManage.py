#!/usr/bin/env python3
# Author: kuronekonano <god772525182@gmail.com>

import cv2
import numpy as np
import pymysql

from PyQt5.QtCore import pyqtSignal, QThread, Qt, QObject
from PyQt5.QtGui import QIcon, QTextCursor
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox, QTableWidgetItem, QAbstractItemView, QProgressBar, \
    QDialog, QHeaderView
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
    sql_name_map = ('stu_id', 'face_id', 'cn_name', 'en_name', 'major', 'grade', 'class', 'sex', 'province', 'nation',
                    'last_attendance_time', 'total_attendance_times', 'create_time')  # 数据库字段映射

    def __init__(self):
        super(DataManageUI, self).__init__()
        loadUi('./ui/DataManage.ui', self)
        self.setWindowIcon(QIcon('./icons/icon.png'))
        # self.setFixedSize(1511, 941)

        # 设置tableWidget只读，不允许修改
        self.tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # 表头自动排序√
        # self.tableWidget.setSortingEnabled(True)

        # 表格双色√
        self.tableWidget.setAlternatingRowColors(True)

        # 表头自动伸缩×
        # self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 取消表格内框线条×
        # self.tableWidget.setFrameStyle(QFrame.NoFrame)

        # 默认选择整行√
        # self.tableWidget.setSelectionBehavior(1)

        # 选择多行开关√
        # self.tableWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)

        # 数据库
        self.database = 'users'
        self.datasets = './datasets'
        self.isDbReady = False
        self.current_select = set()  # 选中内容存储器
        # 连接数据库
        self.initDbButton.clicked.connect(self.initDb)

        # 按住鼠标拖动选择，但是单击选择无效，弃用
        # self.tableWidget.itemEntered.connect(self.enable_delete_button)
        # 获取当前选中的元素，单击选择，按住Ctrl多选，按住shift连续选
        self.tableWidget.itemClicked.connect(self.enable_delete_button)

        # 用户管理
        self.queryUserButton.clicked.connect(self.queryUser)
        self.deleteUserButton.clicked.connect(self.deleteUser)
        self.CellChangeButton.clicked.connect(self.modify_line)  # 启用/禁用编辑功能

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

        # 模糊查询开关
        self.enable_like_select = False
        self.LikeSelectCheckBox.stateChanged.connect(
            lambda: self.is_like_select(self.LikeSelectCheckBox))

    def is_like_select(self, like_select_checkbox):
        if like_select_checkbox.isChecked():
            self.enable_like_select = True
        else:
            self.enable_like_select = False

    # 数据修改提交数据库
    def cell_change(self, row, col):
        try:
            conn, cursor = self.connect_to_sql()

            if not DataRecordUI.table_exists(cursor, self.database):
                raise FileNotFoundError

            item = self.tableWidget.item(row, col)
            stu_id = self.tableWidget.item(row, 0).text()
            after_change_txt = item.text()

            select_sql = 'SELECT * FROM users WHERE stu_id=%s' % stu_id
            cursor.execute(select_sql)
            ret = cursor.fetchall()
            if not ret:
                raise RecordNotFound
            else:
                # print(ret[0])
                before_change_txt = ret[0][col]

            text = '确定将原数据<font color=blue> {} </font>修改为<font color=green> {} </font> 吗？<font color=red>该操作不可逆！</font>'.format(
                before_change_txt, after_change_txt)
            informativeText = '<b>是否继续？</b>'
            ret = DataManageUI.callDialog(QMessageBox.Warning, text, informativeText, QMessageBox.Yes | QMessageBox.No,
                                          QMessageBox.No)

            if ret == QMessageBox.Yes:
                update_sql = 'UPDATE users SET %s="%s" WHERE stu_id=%s' % (
                    self.sql_name_map[col], after_change_txt, stu_id)
                cursor.execute(update_sql)
                self.logQueue.put('修改成功！')
            else:
                if self.CellChangeButton.text() == '禁用编辑':
                    self.tableWidget.cellChanged.disconnect()  # 表格变化时禁用修改监听
                self.tableWidget.setItem(row, col, QTableWidgetItem(str(before_change_txt)))
                if self.CellChangeButton.text() == '禁用编辑':
                    self.enable_write_table()
                # 如果不严格限制修改操作，将无限循环递归触发单元格变动逻辑，直到允许提交

        except FileNotFoundError:
            logging.error('系统找不到数据库表{}'.format(self.database))
            self.isDbReady = False
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：未发现数据库，你可能未进行人脸采集')
        except Exception as e:
            print(e)
            logging.error('读取数据库异常，无法完成数据库初始化')
            self.isDbReady = False
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：读取数据库异常，初始化/刷新数据库失败')
        else:
            cursor.close()
            conn.commit()  # 修改手动commit提交
            conn.close()

        # print(txt)

    @staticmethod
    def connect_to_sql():
        conn = pymysql.connect(host='localhost',
                               user='root',
                               password='970922',
                               db='mytest',
                               port=3306,
                               charset='utf8')
        cursor = conn.cursor()
        return conn, cursor

    # 单元格编辑开关
    def modify_line(self):
        if self.CellChangeButton.text() == '禁用编辑':
            self.tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.CellChangeButton.setText('启用编辑')
            self.enable_select_table()
        else:
            self.deleteUserButton.setEnabled(False)
            self.tableWidget.setEditTriggers(QAbstractItemView.DoubleClicked)
            self.CellChangeButton.setText('禁用编辑')
            self.enable_write_table()

    # 启用编辑时学号和faceID禁止修改
    def enable_write_table(self):
        row_count = self.tableWidget.rowCount()
        for row in range(row_count):
            self.tableWidget.item(row, 0).setFlags(Qt.ItemIsEnabled)
            self.tableWidget.item(row, 1).setFlags(Qt.ItemIsEnabled)
        self.tableWidget.cellChanged.connect(self.cell_change)  # 输出结束后重新关联修改监听

    # 禁用编辑时要将禁止选择的属性修改回来
    def enable_select_table(self):
        self.tableWidget.cellChanged.disconnect()
        row_count = self.tableWidget.rowCount()
        for row in range(row_count):
            self.tableWidget.item(row, 0).setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.tableWidget.item(row, 1).setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        # 一个大坑，所有的setflags枚举类型单独用都是相反的效果，只有用位运算合用才能达到理想的效果

    # 是否执行直方图均衡化
    def enableEqualizeHist(self, equalizeHistCheckBox):
        if equalizeHistCheckBox.isChecked():
            self.isEqualizeHistEnabled = True
        else:
            self.isEqualizeHistEnabled = False

    # 筛选选中数据
    def enable_delete_button(self, item):
        self.current_select.clear()
        select_items = self.tableWidget.selectedItems()[::self.tableWidget.columnCount()]  # 取出所有选择数据中的学号
        self.current_select.update(
            map(lambda x: x.text(), select_items))  # 更新学号信息到set集合中,因为用的是map映射整个list的内容，因此用update而不是add
        print(self.current_select)
        if self.current_select and self.CellChangeButton.text() != '禁用编辑':
            self.deleteUserButton.setEnabled(True)
        else:
            self.deleteUserButton.setEnabled(False)

    # 输出结果至界面表格
    def print_to_table(self, stu_data):
        if self.CellChangeButton.text() == '禁用编辑':
            self.tableWidget.cellChanged.disconnect()  # 表格变化时禁用修改监听
        # 刷新前清空tableWidget
        while self.tableWidget.rowCount() > 0:
            self.tableWidget.removeRow(0)
        # self.tableWidget.setRowCount(0)  # 通过直接设定行数清空表格
        # self.tableWidget.clearContents()  # 删除包含元素，不包括表头，会留下行数
        for row_index, row_data in enumerate(stu_data):
            self.tableWidget.insertRow(row_index)  # 插入行
            for col_index, col_data in enumerate(row_data):  # 插入列
                self.tableWidget.setItem(row_index, col_index, QTableWidgetItem(str(col_data)))  # 设置单元格文本
        if self.CellChangeButton.text() == '禁用编辑':
            self.enable_write_table()

    # 初始化/刷新数据库
    def initDb(self):
        try:
            conn, cursor = self.connect_to_sql()  # 连接数据库

            if not DataRecordUI.table_exists(cursor, self.database):
                raise FileNotFoundError

            cursor.execute('SELECT * FROM users')
            conn.commit()
            stu_data = cursor.fetchall()
            # print(stu_data)
            self.print_to_table(stu_data)  # 输出到表格界面
            cursor.execute('SELECT Count(*) FROM users')  # 学生计数
            result = cursor.fetchone()
            dbUserCount = result[0]
        except FileNotFoundError:
            logging.error('系统找不到数据库表{}'.format(self.database))
            self.isDbReady = False
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：未发现数据库，你可能未进行人脸采集')
        except Exception as e:
            print(e)
            logging.error('读取数据库异常，无法完成数据库初始化')
            self.isDbReady = False
            self.initDbButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：读取数据库异常，初始化/刷新数据库失败')
        else:
            cursor.close()
            conn.close()
            # 人数显示
            self.dbUserCountLcdNum.display(dbUserCount)
            if not self.isDbReady:
                self.isDbReady = True
                self.logQueue.put('Success：数据库初始化完成，发现用户数：{}'.format(dbUserCount))
                self.initDbButton.setText('刷新数据库')  # 改变按钮文本
                self.initDbButton.setIcon(QIcon('./icons/success.png'))
                self.trainButton.setToolTip('')
                self.trainButton.setEnabled(True)  # 启用训练按钮
                self.queryUserButton.setToolTip('')
                self.queryUserButton.setEnabled(True)  # 启用查询按钮
                self.CellChangeButton.setToolTip('')
                self.CellChangeButton.setEnabled(True)  # 启用编辑开关
                self.deleteUserButton.setToolTip('')
            else:
                self.logQueue.put('Success：刷新数据库成功，发现用户数：{}'.format(dbUserCount))

    # 查询用户
    def queryUser(self):
        # 获取输入框学号
        select_data = dict()
        select_data['stu_id'] = self.querystuIDLineEdit.text().strip()
        select_data['cn_name'] = self.queryNameLineEdit.text().strip()
        select_data['en_name'] = self.queryenNameLineEdit.text().strip()
        select_data['major'] = self.queryMajorLineEdit.text().strip()
        select_data['grade'] = self.queryGradeLineEdit.text().strip()
        select_data['class'] = self.queryClassLineEdit.text().strip()
        select_data['province'] = self.queryProvinceLineEdit.text().strip()
        select_data['nation'] = self.queryNationLineEdit.text().strip()
        # print(select_data)
        conn, cursor = self.connect_to_sql()

        try:
            select_sql = 'SELECT * FROM users WHERE 1=1'
            for key, value in select_data.items():
                if value is not '':
                    if self.enable_like_select:
                        select_sql += ' AND %s LIKE "%%%s%%"' % (key, value)
                    else:
                        select_sql += ' AND %s LIKE "%s"' % (key, value)
            # print(select_sql)
            cursor.execute(select_sql)
            ret = cursor.fetchall()
            if not ret:
                raise RecordNotFound
            self.print_to_table(ret)
        except RecordNotFound:
            self.queryUserButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：此用户不存在')
            logging.warning('用户不存在{}'.format(str(select_data)))
            text = 'Error!'
            informativeText = '<b>此用户不存在。</b>'
            DataRecordUI.callDialog(QMessageBox.Critical, text, informativeText, QMessageBox.Ok)
        except Exception as e:
            print(e)
            logging.error('读取数据库异常，无法查询到{}的用户信息'.format(str(select_data)))
            self.queryUserButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：读取数据库异常，查询失败')
        else:
            # 查询结果显示
            self.logQueue.put('查询成功！')
            self.queryUserButton.setIcon(QIcon('./icons/success.png'))
            self.deleteUserButton.setEnabled(True)  # 删除按钮启用
        finally:
            cursor.close()
            conn.close()

    # 删除用户
    def deleteUser(self):
        del_user = tuple(self.current_select)
        if len(del_user) == 1:
            str_del_user = '(' + str(del_user[0]) + ')'  # 元组只有一个元素的时候会多逗号
        else:
            str_del_user = str(del_user)
        text = '已选择{}个用户。从数据库中删除选中用户，同时删除相应人脸数据，<font color=red>该操作不可逆！</font>'.format(len(del_user))
        informativeText = '<b>是否继续？</b>'
        ret = DataManageUI.callDialog(QMessageBox.Warning, text, informativeText, QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)

        if ret == QMessageBox.Yes:
            conn, cursor = self.connect_to_sql()

            del_sql = 'DELETE FROM users WHERE stu_id IN %s' % str_del_user
            # print(del_sql)
            try:
                cursor.execute(del_sql)
            except Exception as e:
                print(e)
                cursor.close()
                logging.error('无法从数据库中删除{}'.format(del_user))
                self.deleteUserButton.setIcon(QIcon('./icons/error.png'))
                self.logQueue.put('Error：读写数据库异常，删除失败')
            else:
                cursor.close()
                conn.commit()  # 删除手动commit提交
                for stu_id in del_user:
                    if os.path.exists('{}/stu_{}'.format(self.datasets, stu_id)):
                        try:
                            shutil.rmtree('{}/stu_{}'.format(self.datasets, stu_id))
                        except Exception as e:
                            logging.error('系统无法删除删除{}/stu_{}'.format(self.datasets, stu_id))
                            self.logQueue.put('Error：删除人脸数据失败，请手动删除{}/stu_{}目录'.format(self.datasets, stu_id))

                text = '你已成功删除{}个用户记录。'.format(len(del_user))
                informativeText = '<b>请在右侧菜单重新训练人脸数据。</b>'
                DataManageUI.callDialog(QMessageBox.Information, text, informativeText, QMessageBox.Ok)
                # 删除用户后重新读取数据库
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
        face_cascade = cv2.CascadeClassifier('./haarcascades/haarcascade_frontalface_default.xml')  # 加载分类器
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

        conn, cursor = self.connect_to_sql()

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

    # LOG输出
    def logOutput(self, log):
        # 加入时间前缀
        time = datetime.now().strftime('[%Y/%m/%d %H:%M:%S]')
        log = time + ' ' + log + '\n'

        self.logTextEdit.moveCursor(QTextCursor.End)  # 日志光标挪至底部
        self.logTextEdit.insertPlainText(log)  # 插入日志消息
        self.logTextEdit.ensureCursorVisible()  # 自动滚屏

    # 系统对话框
    @staticmethod
    def callDialog(icon, text, informativeText, standardButtons, defaultButton=None):
        msg = QMessageBox()
        msg.setWindowIcon(QIcon('./icons/icon.png'))
        msg.setWindowTitle('人脸识别考勤管理系统 - DataManage')
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
