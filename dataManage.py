#!/usr/bin/env python3
# Author: kuronekonano <god772525182@gmail.com>
import csv
import re

import cv2
import dlib
import numpy as np
import pymysql
import xlwt as ExcelWrite
from xlwt import Borders, XFStyle, Pattern

from PyQt5.QtCore import pyqtSignal, QThread, Qt, QObject
from PyQt5.QtGui import QIcon, QTextCursor
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox, QTableWidgetItem, QAbstractItemView, QProgressBar, \
    QDialog, QHeaderView
from PyQt5.uic import loadUi

import logging
import logging.config
import os
import shutil
import sys
import threading
import multiprocessing

from datetime import datetime
from dataRecord import DataRecordUI

haar_face_cascade = cv2.CascadeClassifier('./haarcascades/haarcascade_frontalface_default.xml')  # 加载分类器
predictor_5 = dlib.shape_predictor('./shape_predictor_5_face_landmarks.dat')  # 5特征点模型
predictor_68 = dlib.shape_predictor('./shape_predictor_68_face_landmarks.dat')  # 68特征点模型
face_rec = dlib.face_recognition_model_v1("dlib_face_recognition_resnet_model_v1.dat")  # 人脸识别器模型
dlib_detector = dlib.get_frontal_face_detector()  # dlib 人脸检测器


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
        # self.setFixedSize(1511, 941)  # 加上后就规定了窗口大小，且不可缩放

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
        self.ExportExcelpushButton.clicked.connect(self.check_table)

        # 直方图均衡化
        self.isEqualizeHistEnabled = False
        self.equalizeHistCheckBox.stateChanged.connect(
            lambda: self.enableEqualizeHist(self.equalizeHistCheckBox))

        # 训练人脸数据
        self.trainButton.clicked.connect(self.train)
        self.dlibButton.clicked.connect(self.train_by_dlib)

        # 系统日志
        self.receiveLogSignal.connect(lambda log: self.logOutput(log))
        self.logOutputThread = threading.Thread(target=self.receiveLog, daemon=True)
        self.logOutputThread.start()

        # 模糊查询开关
        self.enable_like_select = False
        self.LikeSelectCheckBox.stateChanged.connect(
            lambda: self.is_like_select(self.LikeSelectCheckBox))

    # 模糊查询开关
    def is_like_select(self, like_select_checkbox):
        if like_select_checkbox.isChecked():
            self.enable_like_select = True
        else:
            self.enable_like_select = False

    def check_table(self):
        self.export_excel_dialog = ExportExcelDialog()
        self.export_excel_dialog.exec()

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

    # 数据库连接
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
        # print(self.current_select)
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
            attendance_rate = round(row_data[11]/(row_data[10] if row_data[10] != 0 else 1), 5) * 100
            self.tableWidget.setItem(row_index, len(row_data), QTableWidgetItem(str(attendance_rate) + '%'))  # 设置单元格文本

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
                self.trainButton.setEnabled(True)  # 启用LBPH训练按钮
                self.queryUserButton.setToolTip('')
                self.queryUserButton.setEnabled(True)  # 启用查询按钮
                self.CellChangeButton.setToolTip('')
                self.CellChangeButton.setEnabled(True)  # 启用编辑开关
                self.deleteUserButton.setToolTip('')
                self.ExportExcelpushButton.setEnabled(True)  # 启用导出表格按钮
                self.dlibButton.setToolTip('')
                self.dlibButton.setEnabled(True)  # 启用dlib训练按钮
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

    # dlib人脸特征提取
    def train_by_dlib(self):
        try:
            if not os.path.isdir(self.datasets):
                raise FileNotFoundError

            text = '系统将开始提取人脸特征，界面会暂停响应一段时间，完成后会弹出提示。'
            informativeText = '<b>训练过程请勿进行其它操作，是否继续？</b>'
            ret = DataManageUI.callDialog(QMessageBox.Question, text, informativeText,
                                          QMessageBox.Yes | QMessageBox.No,
                                          QMessageBox.No)
            if ret == QMessageBox.Yes:
                progress_bar = ActionsTrainByDlib(self)
        except FileNotFoundError:
            logging.error('系统找不到人脸数据目录{}'.format(self.datasets))
            self.dlibButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('未发现人脸数据目录{}，你可能未进行人脸采集'.format(self.datasets))
        except Exception as e:
            logging.error('遍历人脸库出现异常，训练人脸数据失败')
            self.dlibButton.setIcon(QIcon('./icons/error.png'))
            self.logQueue.put('Error：遍历人脸库出现异常，训练失败')
        else:
            text = '<font color=green><b>Success!</b></font> 系统已生成./dlib_128D_csv/features_all.csv'
            informativeText = '<b>人脸特征提取完成！</b>'
            DataManageUI.callDialog(QMessageBox.Information, text, informativeText, QMessageBox.Ok)
            self.dlibButton.setIcon(QIcon('./icons/success.png'))
            self.logQueue.put('Success：dlib人脸数据特征提取完成')
            self.initDb()

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
                progress_bar = ActionsTrainByLBPH(self)
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


# LBPH进度条
class ActionsTrainByLBPH(QDialog):
    """
    Simple dialog that consists of a Progress Bar and a Button.
    Clicking on the button results in the start of a timer and
    updates the progress bar.
    """

    def __init__(self, datamanage):
        super(ActionsTrainByLBPH, self).__init__()
        self.data_manage = datamanage
        self.initUI()

    def initUI(self):
        self.setWindowTitle('正在训练模型...')
        self.progress = QProgressBar(self)
        self.progress.setGeometry(0, 0, 300, 25)
        self.progress.setMaximum(100)
        self.train_data = TrainData(self.data_manage)  # 导入图片线程实例
        self.train_data.progress_bar_signal.connect(self.onCountChanged)  # 信号槽函数绑定
        self.train_data.start()
        self.exec()
        # 注意此处有坑，进度条对话框应该使用exec()事件循环而不是show()，使用show()与QThread时会导致对话框无法完全结束，后续语句无法执行

    def onCountChanged(self, value):
        self.progress.setValue(value)
        if value >= 100:
            self.close()
    # 关于训练过程独立出线程执行，并使用进度条更新的方法
    # 因为训练过程比较耗时的是检测脸与读取图片数据集，并且只有此处是循环每个人的遍历
    # 因此将进度条主要展现的是读取数据，而不是训练数据，训练数据耗时相对不多，因此完全结束后只占进度条的1%
    # 为实现训练函数的整个过程，将读取数据，训练数据，脸部检测 的处理函数全部挪到该线程中执行


# LBPH模型训练
class TrainData(QThread):
    progress_bar_signal = pyqtSignal(float)

    def __init__(self, data_manage):
        super(TrainData, self).__init__()
        self.data_manage = data_manage

    def run(self) -> None:
        face_recognizer = cv2.face.LBPHFaceRecognizer_create()
        if not os.path.exists('./recognizer'):
            os.makedirs('./recognizer')
        faces, labels = self.prepareTrainingData(self.data_manage.datasets)  # 准备图片数据
        face_recognizer.train(faces, np.array(labels))
        face_recognizer.save('./recognizer/trainingData.yml')
        self.progress_bar_signal.emit(100)

    # 准备图片数据，参数为数据集路径
    def prepareTrainingData(self, data_folder_path):
        dirs = os.listdir(data_folder_path)  # 返回指定的文件夹包含的文件或文件夹的名字的列表
        faces = []
        labels = []

        face_id = 1

        conn, cursor = DataManageUI.connect_to_sql()
        people_count = len(dirs)
        # 遍历人脸库
        for index, dir_name in enumerate(dirs):
            bar = index / people_count * 100
            self.progress_bar_signal.emit(bar)
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
                DataManageUI.logQueue.put('发现学号为{}的人脸数据，但数据库中找不到相应记录，已忽略'.format(stu_id))
                continue
            subject_dir_path = os.path.join(data_folder_path, dir_name)  # 子目录
            subject_images_names = os.listdir(subject_dir_path)  # 获取所有图片名
            for image_name in subject_images_names:
                if image_name.startswith('.'):  # 忽略隐藏文件
                    continue
                image_path = os.path.join(subject_dir_path, image_name)
                image = cv2.imread(image_path)  # 读取图片
                face, rect = self.detectFace(image)  # 探测人脸，返回
                if face is not None:
                    faces.append(face)  # 检测到的脸放入list
                    labels.append(face_id)  # face_id放入标签，同一个人的脸同一个face_id
            face_id = face_id + 1

        cursor.close()
        conn.commit()
        conn.close()

        return faces, labels

    # haar检测人脸
    def detectFace(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)  # 灰度图
        if self.data_manage.isEqualizeHistEnabled:  # 直方均衡化
            gray = cv2.equalizeHist(gray)
        faces = haar_face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5, minSize=(90, 90))  # 抠脸

        if len(faces) == 0:
            return None, None
        (x, y, w, h) = faces[0]
        return gray[y:y + w, x:x + h], faces[0]


# LBPH进度条
class ActionsTrainByDlib(QDialog):
    """
    Simple dialog that consists of a Progress Bar and a Button.
    Clicking on the button results in the start of a timer and
    updates the progress bar.
    """

    def __init__(self, datamanage):
        super(ActionsTrainByDlib, self).__init__()
        self.data_manage = datamanage
        self.initUI()

    def initUI(self):
        self.setWindowTitle('正在训练模型...')
        self.progress = QProgressBar(self)
        self.progress.setGeometry(0, 0, 300, 25)
        self.progress.setMaximum(100)
        self.train_data_by_dlib = TrainDataByDlib(self.data_manage)  # 导入图片线程实例
        self.train_data_by_dlib.progress_bar_signal.connect(self.onCountChanged)  # 信号槽函数绑定
        self.train_data_by_dlib.start()
        self.exec()  # 消息循环
        # 注意此处有坑，进度条对话框应该使用exec()事件循环而不是show()，使用show()与QThread时会导致对话框无法完全结束，后续语句无法执行

    def onCountChanged(self, value):
        self.progress.setValue(value)
        if value >= 100:
            self.close()


# Dlib特征点提取
class TrainDataByDlib(QThread):
    progress_bar_signal = pyqtSignal(float)

    def __init__(self, data_manage):
        super(TrainDataByDlib, self).__init__()
        self.data_manage = data_manage

    def run(self) -> None:
        if not os.path.exists('./dlib_128D_csv'):
            os.makedirs('./dlib_128D_csv')
        data_folder_path = self.data_manage.datasets  # 准备图片数据

        dirs = os.listdir(data_folder_path)  # 返回指定的文件夹包含的文件或文件夹的名字的列表

        face_id = 1

        conn, cursor = DataManageUI.connect_to_sql()
        people_count = len(dirs)
        # 遍历人脸库
        with open('./dlib_128D_csv/features_all.csv', 'w', newline="") as csvfile:
            writer = csv.writer(csvfile)
            for index, dir_name in enumerate(dirs):
                bar = index / people_count * 100
                self.progress_bar_signal.emit(bar)
                if not dir_name.startswith('stu_'):  # 跳过不合法命名的图片集
                    continue
                stu_id = dir_name.replace('stu_', '')  # 获取图片集对应的学号
                try:
                    cursor.execute('SELECT * FROM users WHERE stu_id=%s', (stu_id,))  # 根据学号查询学生信息
                    ret = cursor.fetchall()
                    if not ret:
                        raise RecordNotFound  # 在try里raise错误类型，在except里再处理
                    cursor.execute('UPDATE users SET face_id=%s WHERE stu_id=%s',
                                   (face_id, stu_id,))  # 对可以训练的人脸设置face_id
                except RecordNotFound:
                    logging.warning('数据库中找不到学号为{}的用户记录'.format(stu_id))
                    DataManageUI.logQueue.put('发现学号为{}的人脸数据，但数据库中找不到相应记录，已忽略'.format(stu_id))
                    continue
                subject_dir_path = os.path.join(data_folder_path, dir_name)  # 子目录
                subject_images_names = os.listdir(subject_dir_path)  # 获取所有图片名
                one_person_all_features = []
                for image_name in subject_images_names:
                    if image_name.startswith('.'):  # 忽略隐藏文件
                        continue
                    image_path = os.path.join(subject_dir_path, image_name)
                    face_features = self.cal_128D_features(image_path)  # 探测人脸，返回
                    if face_features == 0:
                        continue
                    one_person_all_features.append(face_features)
                if one_person_all_features:
                    features_mean = np.array(one_person_all_features).mean(axis=0)
                else:
                    features_mean = np.zeros(128, dtype=int, order='C')
                face_id_list = np.full(128, face_id, dtype=int, order='C')
                writer.writerow(face_id_list)
                writer.writerow(features_mean)
                face_id = face_id + 1

        cursor.close()
        conn.commit()
        conn.close()

        self.progress_bar_signal.emit(100)

    # 检测人脸
    def cal_128D_features(self, img_path):
        img = cv2.imread(img_path)  # 读取图片
        faces = dlib_detector(img, 1)  # 抠脸
        if len(faces) == 0:
            print("No Face!")
            return 0
        shape = predictor_68(img, faces[0])  # 提取脸部特征点
        features = face_rec.compute_face_descriptor(img, shape)  # 计算特征值
        return features


class ExportExcelDialog(QDialog):

    def __init__(self):
        super(ExportExcelDialog, self).__init__()
        loadUi('./ui/export_excel.ui', self)
        self.setWindowIcon(QIcon('./icons/icon.png'))

        # 只读，不允许修改
        self.show_sqlTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.StuCheckTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # 表头自动伸缩×
        self.show_sqlTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.StuCheckTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self.select_table_pushButton.clicked.connect(self.select_table_show)
        self.export_pushButton.clicked.connect(self.export_to_excel)
        self.DelpushButton.clicked.connect(self.del_table)
        self.fresh_table_list()

    # 刷新数据库表格
    def fresh_table_list(self):
        conn, cursor = DataManageUI.connect_to_sql()
        table_list = self.get_sql_table(cursor)
        cursor.close()
        conn.commit()
        conn.close()
        self.print_sql_tablelist(table_list)

    # 获取数据库表名
    @staticmethod
    def get_sql_table(cursor):
        sql = "show tables;"
        cursor.execute(sql)
        tables = [cursor.fetchall()]
        table_list = re.findall('(\'.*?\')', str(tables))
        table_list = [re.sub("'", '', each) for each in table_list]
        return table_list

    # 输出表名到表格中
    def print_sql_tablelist(self, table_list):
        while self.show_sqlTable.rowCount() > 0:
            self.show_sqlTable.removeRow(0)
        for row_index, row_data in enumerate(table_list):
            self.show_sqlTable.insertRow(row_index)  # 插入行
            self.show_sqlTable.setItem(row_index, 0, QTableWidgetItem(str(row_data)))  # 设置单元格文本

    # 选择表格并预览内容
    def select_table_show(self):
        if not self.show_sqlTable.selectedItems():
            return
        self.select_table = self.show_sqlTable.selectedItems()[0].text()

        # print(select_table)
        try:
            conn, cursor = DataManageUI.connect_to_sql()

            if not DataRecordUI.table_exists(cursor, self.select_table):
                raise FileNotFoundError
            sql_select = 'SELECT * FROM `%s`' % self.select_table
            cursor.execute(sql_select)
            conn.commit()
            stu_data = cursor.fetchall()
            attendance_cnt = 0  # 出席人数计数
            if len(stu_data[0]) != self.StuCheckTable.columnCount():
                text = 'Error!'
                informativeText = '<b>表格格式不正确，请重新选择正确的签到表格。</b>'
                DataRecordUI.callDialog(QMessageBox.Critical, text, informativeText, QMessageBox.Ok)
                return
            while self.StuCheckTable.rowCount() > 0:
                self.StuCheckTable.removeRow(0)
            for row_index, row_data in enumerate(stu_data):
                self.StuCheckTable.insertRow(row_index)  # 插入行
                if row_data[2] == 1:
                    attendance_cnt += 1
                for col_index, col_data in enumerate(row_data):  # 插入列
                    self.StuCheckTable.setItem(row_index, col_index, QTableWidgetItem(str(col_data)))  # 设置单元格文本
            self.export_pushButton.setEnabled(True)
            self.DelpushButton.setEnabled(True)
            attendance_rate = attendance_cnt / len(stu_data) * 100
            if 90 > attendance_rate >= 60:
                self.attendance_label.setText('<b>出勤率：{}%</b>'.format(attendance_rate))
            elif attendance_rate < 60:
                self.attendance_label.setText('<b>出勤率：<font color=red>{}%</font></b>'.format(attendance_rate))
            elif 100 > attendance_rate >= 90:
                self.attendance_label.setText('<b>出勤率：<font color=green>{}%</font></b>'.format(attendance_rate))
            else:
                self.attendance_label.setText('<b>出勤率：<font color=blue>{}%</font></b>'.format(attendance_rate))
        except FileNotFoundError:
            logging.error('系统找不到数据库表{}'.format(self.select_table))
        except Exception as e:
            print(e)
            logging.error('读取数据库异常，无法完成数据库查询')
        else:
            cursor.close()
            conn.close()

    # 导出最后一次选择的表格
    def export_to_excel(self):
        if not os.path.isdir('./export_excel'):  # 导出结果存储目录
            os.makedirs('./export_excel')
        save_path = os.path.join('./export_excel', self.select_table + '.xls')
        head_list = ['学号', '姓名', '是否出勤', '出勤时间']
        xls = ExcelWrite.Workbook()  # 创建Excel控制对象
        sheet = xls.add_sheet("Sheet1")  # 创建被写入的表格sheet1
        style = XFStyle()
        pattern = Pattern()  # 创建一个模式
        pattern.pattern = Pattern.SOLID_PATTERN  # 设置其模式为实型
        pattern.pattern_fore_colour = 0x16  # 设置其模式单元格背景色
        # 设置单元格背景颜色 0 = Black, 1 = White, 2 = Red, 3 = Green, 4 = Blue, 5 = Yellow, 6 = Magenta,  the list goes on...
        style.pattern = pattern
        for col in range(len(head_list)):  # 写入首行信息，为表头，表示列名
            sheet.write(0, col, head_list[col], style)
            sheet.col(col).width = 4240

        try:
            # 连接数据库读取数据
            conn, cursor = DataManageUI.connect_to_sql()
            sql = 'select * from `%s`' % self.select_table
            cursor.execute(sql)
            row = 0
            stu_data = cursor.fetchall()
            for stu_info in stu_data:  # 遍历数据库中每行信息，一行表示一部电影的所有信息
                stu_info = list(stu_info)
                if stu_info[3]:
                    stu_info[3] = stu_info[3].strftime('%Y/%m/%d %H:%M:%S')
                row = row + 1  # 第0行为表头，不添加数据，因此从第一列开始写入
                for col in range(len(stu_info)):  # 对于一行信息进行遍历，分别存入每列
                    sheet.write(row, col, stu_info[col])

            xls.save(save_path)  # 写入完成，存储
            cursor.close()
            conn.close()
            text = 'Success!'
            informativeText = '<b>课程{}签到表 导出成功! 目标路径：./export_excel</b>'.format(self.select_table)
            DataRecordUI.callDialog(QMessageBox.Information, text, informativeText, QMessageBox.Ok)
        except Exception as e:
            print(e)
            text = 'Error!'
            informativeText = '<b>导出失败!</b>'
            DataRecordUI.callDialog(QMessageBox.Critical, text, informativeText, QMessageBox.Ok)

    # 删除表格
    def del_table(self):
        self.select_table = self.show_sqlTable.selectedItems()[0].text()
        text = '确定<font color=blue> 删除 </font>表格<font color=blue> {} </font> 吗？<font color=red>该操作不可逆！</font>'.format(
            self.select_table)
        informativeText = '<b>是否继续？</b>'
        ret = DataManageUI.callDialog(QMessageBox.Warning, text, informativeText, QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)

        if ret == QMessageBox.Yes:
            sql_del_table = 'DROP TABLE `%s`' % self.select_table
            try:
                conn, cursor = DataManageUI.connect_to_sql()

                if not DataRecordUI.table_exists(cursor, self.select_table):
                    raise FileNotFoundError
                cursor.execute(sql_del_table)
                conn.commit()
                text = 'Success!'
                informativeText = '<b>{} 签到表 已删除！</b>'.format(self.select_table)
                DataRecordUI.callDialog(QMessageBox.Information, text, informativeText, QMessageBox.Ok)
            except FileNotFoundError:
                logging.error('系统找不到数据库表{}'.format(self.select_table))
            except Exception as e:
                print(e)
                text = 'Error!'
                informativeText = '<b>无法删除!</b>'
                DataRecordUI.callDialog(QMessageBox.Critical, text, informativeText, QMessageBox.Ok)
            else:
                cursor.close()
                conn.close()
            self.fresh_table_list()


if __name__ == '__main__':
    logging.config.fileConfig('./config/logging.cfg')
    app = QApplication(sys.argv)
    window = DataManageUI()
    window.show()
    sys.exit(app.exec())
