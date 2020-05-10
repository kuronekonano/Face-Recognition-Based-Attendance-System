from PyQt5.QtWidgets import QWidget, QHBoxLayout, QTableWidget, QPushButton, QApplication, QVBoxLayout, \
    QTableWidgetItem, QCheckBox, QAbstractItemView, QHeaderView, QLabel, QFrame
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
from faker import Factory
import random
import sys
import numpy as np
import matplotlib.pyplot as plt
from skimage.feature import local_binary_pattern
from skimage import data
from skimage.color import label2rgb
from skimage.transform import rotate


class ui(QWidget):
    def __init__(self):
        super().__init__()
        self.setupUI()
        self.id = 1
        self.lines = []  # 维护一个list记录表格中所有数据
        self.editable = True
        self.des_sort = True
        self.faker = Factory.create()
        self.btn_add.clicked.connect(self.add_line)
        self.btn_del.clicked.connect(self.del_line)  # 删除
        self.btn_modify.clicked.connect(self.modify_line)  # 允许编辑
        self.btn_select_line.clicked.connect(self.select_line)  # 选择整行开关
        self.btn_select_single.clicked.connect(self.deny_muti_line)  # 选择多行开关
        self.btn_sort.clicked.connect(self.sortItem)  # 按分数排序
        self.btn_set_header.clicked.connect(self.setheader)
        self.btn_set_middle.clicked.connect(self.middle)  # 文字居中加颜色
        self.table.cellChanged.connect(self.cellchange)  # 单元格内容变动
        self.btn_noframe.clicked.connect(self.noframe)

    #     # Sess = sessionmaker(bind = engine)
    def setupUI(self):
        self.setWindowTitle('欢迎加入微信公众号:python玩转网络 ')
        self.resize(640, 480)
        self.table = QTableWidget(self)
        self.btn_add = QPushButton('增加')
        self.btn_del = QPushButton('删除')
        self.btn_modify = QPushButton('可以编辑')
        self.btn_select_line = QPushButton('选择整行')
        self.btn_select_single = QPushButton('禁止选多行')
        self.btn_sort = QPushButton('以分数排序')
        self.btn_set_header = QPushButton('标头设置')
        self.btn_set_middle = QPushButton('文字居中加颜色')
        self.btn_noframe = QPushButton('取消边框颜色交替')
        self.spacerItem = QtWidgets.QSpacerItem(20, 20, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.vbox = QVBoxLayout()
        self.vbox.addWidget(self.btn_add)
        self.vbox.addWidget(self.btn_del)
        self.vbox.addWidget(self.btn_modify)
        self.vbox.addWidget(self.btn_select_line)
        self.vbox.addWidget(self.btn_select_single)
        self.vbox.addWidget(self.btn_sort)
        self.vbox.addWidget(self.btn_set_header)
        self.vbox.addWidget(self.btn_set_middle)
        self.vbox.addWidget(self.btn_noframe)
        self.vbox.addSpacerItem(self.spacerItem)  # 可以用addItem也可以用addSpacerItem方法添加，没看出哪里不一样
        self.txt = QLabel()
        self.txt.setMinimumHeight(50)
        self.vbox2 = QVBoxLayout()
        self.vbox2.addWidget(self.table)
        self.vbox2.addWidget(self.txt)
        self.hbox = QHBoxLayout()
        self.hbox.addLayout(self.vbox2)
        self.hbox.addLayout(self.vbox)
        self.setLayout(self.hbox)
        self.table.setColumnCount(5)  ##设置列数
        self.headers = ['id', '选择', '姓名', '成绩', '住址']
        self.table.setHorizontalHeaderLabels(self.headers)
        self.show()

    # 增加数据
    def add_line(self):
        self.table.cellChanged.disconnect()
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        id = str(self.id)
        ck = QCheckBox()  # 复选框实例
        h = QHBoxLayout()
        h.setAlignment(Qt.AlignCenter)
        h.addWidget(ck)  # 设置复选框
        w = QWidget()
        w.setLayout(h)
        name = self.faker.name()  # 自动创建假名
        score = str(random.randint(50, 99))  # 随机生成分数
        add = self.faker.address()  # 自动创建假地址
        self.table.setItem(row, 0, QTableWidgetItem(id))
        self.table.setCellWidget(row, 1, w)
        self.table.setItem(row, 2, QTableWidgetItem(name))
        self.table.setItem(row, 3, QTableWidgetItem(score))
        self.table.setItem(row, 4, QTableWidgetItem(add))
        self.id += 1
        self.lines.append([id, ck, name, score, add])  # 增加数据时插入新list
        self.settext('自动生成随机一行数据！,checkbox设置为居中显示')
        self.table.cellChanged.connect(self.cellchange)

    def del_line(self):
        removeline = []
        for line in self.lines:  # 遍历list相当于遍历了当前表格中所有数据
            if line[1].isChecked():  # 列表中的复选框状态可以改变，如果当前行被选中
                row = self.table.rowCount()  # 当前行数
                for x in range(row, 0, -1):  # 倒叙遍历所有行
                    if line[0] == self.table.item(x - 1, 0).text():  # 若当前行的学号等于表格中正在遍历行的id，则删除这一行
                        self.table.removeRow(x - 1)
                        removeline.append(line)
        for line in removeline:  # 因为无法一边遍历一边删
            self.lines.remove(line)
        self.settext('删除在左边checkbox中选中的行，使用了一个笨办法取得行号\n，不知道有没有其他可以直接取得行号的方法！')

    # 单元格编辑
    def modify_line(self):
        if self.editable:
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.btn_modify.setText('禁止编辑')
            self.editable = False
        else:
            self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
            self.btn_modify.setText('可以编辑')
            self.editable = True
        self.settext('设置，是否可以编辑整个表格')

    # 选择整行开关
    def select_line(self):
        if self.table.selectionBehavior() == 0:
            self.table.setSelectionBehavior(1)
            self.btn_select_line.setStyleSheet('background-color:lightblue')
        else:
            self.table.setSelectionBehavior(0)
            self.btn_select_line.setStyleSheet('')
        self.settext('默认时，点击单元格，只可选择一个格，此处设置为可选择整行')

    # 选择多行开关
    def deny_muti_line(self):
        if self.table.selectionMode() in [2, 3]:
            self.table.setSelectionMode(QAbstractItemView.SingleSelection)
            self.btn_select_single.setStyleSheet('background-color:lightblue')
        else:
            self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.btn_select_single.setStyleSheet('')
        self.settext('点击时会轮换以多行或单行选择，默认是可以同时选择多行')

    # 单元格排序
    def sortItem(self):
        if self.des_sort == True:
            self.table.sortItems(3, Qt.DescendingOrder)
            self.des_sort = False
            self.btn_sort.setStyleSheet('background-color:lightblue')  # 按分数排序
            self.table.setSortingEnabled(True)  # 设置表头可以自动排序
        else:
            self.table.sortItems(3, Qt.AscendingOrder)
            self.des_sort = True
            self.btn_sort.setStyleSheet('background-color:lightblue')
            self.table.setSortingEnabled(False)  # 设置表头可以自动排序
        self.settext('点击时会轮换以升序降序排列，但排序时，会使自动列宽失效！')

    def setheader(self):
        font = QFont('微软雅黑', 12)
        font.setBold(True)
        self.table.horizontalHeader().setFont(font)  # 设置表头字体
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 50)
        self.table.setColumnWidth(3, 100)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setStyleSheet('QHeaderView::section{background:gray}')
        self.table.horizontalHeader().setFixedHeight(50)
        self.table.setColumnHidden(0, True)
        self.btn_set_header.setStyleSheet('background-color:lightblue')
        self.settext('设置标头字体及字号，隐藏ID列，设置标头除姓名外全部为固定宽度\n，设置姓名列自动扩展宽度，设置标头行高，设置标头背景色')

    def middle(self):
        self.btn_set_middle.setStyleSheet('background-color:lightblue')
        self.table.setStyleSheet('color:green;')
        row = self.table.rowCount()
        for x in range(row):
            for y in range(4):
                if y != 1:
                    item = self.table.item(x, y)
                    item.setTextAlignment(Qt.AlignCenter)
                else:
                    pass
        self.btn_set_middle.setStyleSheet('background-color:lightblue')
        self.settext('将文字居中显示,设置文字颜色')

    # 保存更改数据之后的逻辑
    def cellchange(self, row, col):
        item = self.table.item(row, col)
        txt = item.text()
        self.settext('第%s行，第%s列 , 数据改变为:%s' % (row, col, txt))

    def noframe(self):
        self.table.setAlternatingRowColors(True)  # 表格双色
        self.table.setFrameStyle(QFrame.NoFrame)  # 取消表格内框线条
        self.table.setStyleSheet('color:green;'
                                 'gridline-color:white;'
                                 'border:0px solid gray')
        self.settext('取消表的框线,\n 取消表格内框')

    # 设置下方状态提示文本
    def settext(self, txt):
        font = QFont('微软雅黑', 10)
        self.txt.setFont(font)
        self.txt.setText(txt)


if __name__ == '__main__':
    # app = QApplication(sys.argv)
    # ui = ui()
    # sys.exit(app.exec_())
    # settings for LBP
    radius = 2
    n_points = 8 * radius
    METHOD = 'uniform'

    def hist(ax, lbp):
        n_bins = int(lbp.max() + 1)
        return ax.hist(lbp.ravel(), density=True, bins=n_bins, range=(0, n_bins),
                       facecolor='0.5')

    def kullback_leibler_divergence(p, q):
        p = np.asarray(p)
        q = np.asarray(q)
        filt = np.logical_and(p != 0, q != 0)
        return np.sum(p[filt] * np.log2(p[filt] / q[filt]))


    def match(refs, img):
        best_score = 10
        best_name = None
        lbp = local_binary_pattern(img, n_points, radius, METHOD)
        n_bins = int(lbp.max() + 1)
        hist, _ = np.histogram(lbp, normed=True, bins=n_bins, range=(0, n_bins))
        for name, ref in refs.items():
            ref_hist, _ = np.histogram(ref, normed=True, bins=n_bins,
                                       range=(0, n_bins))
            score = kullback_leibler_divergence(hist, ref_hist)
            if score < best_score:
                best_score = score
                best_name = name
        return best_name


    brick = data.brick()
    grass = data.grass()
    wall = data.rough_wall()


    refs = {
        'brick': local_binary_pattern(brick, n_points, radius, METHOD),
        'grass': local_binary_pattern(grass, n_points, radius, METHOD),
        'wall': local_binary_pattern(wall, n_points, radius, METHOD)
    }

    # classify rotated textures
    print('Rotated images matched against references using LBP:')
    print('original: brick, rotated: 30deg, match result: ',
          match(refs, rotate(brick, angle=30, resize=False)))
    print('original: brick, rotated: 70deg, match result: ',
          match(refs, rotate(brick, angle=70, resize=False)))
    print('original: grass, rotated: 145deg, match result: ',
          match(refs, rotate(grass, angle=145, resize=False)))

    # plot histograms of LBP of textures
    fig, ((ax1, ax2, ax3), (ax4, ax5, ax6)) = plt.subplots(nrows=2, ncols=3,
                                                           figsize=(9, 6))
    plt.gray()

    ax1.imshow(brick)
    ax1.axis('off')
    hist(ax4, refs['brick'])
    ax4.set_ylabel('Percentage')

    ax2.imshow(grass)
    ax2.axis('off')
    hist(ax5, refs['grass'])
    ax5.set_xlabel('Uniform LBP values')

    ax3.imshow(wall)
    ax3.axis('off')
    hist(ax6, refs['wall'])

    plt.show()
