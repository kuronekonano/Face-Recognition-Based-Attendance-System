# -*- coding: utf-8 -*-

###########################################################################
## Python code generated with wxFormBuilder (version Jun 17 2015)
## http://www.wxformbuilder.org/
## by Kuroneko
## PLEASE DO "NOT" EDIT THIS FILE!
###########################################################################
import pymysql
import wx
import wx.xrc


###########################################################################
## Class loginFrame
###########################################################################

class loginFrame(wx.Frame):

    def __init__(self, parent):  # 框体布局
        wx.Frame.__init__(self, parent, id=wx.ID_ANY, title=u"KuroNeko_Client——欢迎", pos=wx.DefaultPosition,
                          size=wx.Size(289, 153), style=wx.DEFAULT_FRAME_STYLE | wx.TAB_TRAVERSAL)

        self.SetSizeHints(wx.DefaultSize, wx.DefaultSize)
        self.SetBackgroundColour(wx.Colour(170, 255, 170))
        fgSizer6 = wx.FlexGridSizer(0, 2, 0, 0)
        fgSizer6.SetFlexibleDirection(wx.BOTH)
        fgSizer6.SetNonFlexibleGrowMode(wx.FLEX_GROWMODE_SPECIFIED)

        self.username_text = wx.StaticText(self, wx.ID_ANY, u"用户名:", wx.DefaultPosition, wx.Size(100, -1), 0)  # 用户名标签
        self.username_text.Wrap(-1)
        self.username_text.SetFont(wx.Font(16, 70, 90, 90, False, "黑体"))
        self.username_text.SetForegroundColour(wx.Colour(255, 128, 0))

        fgSizer6.Add(self.username_text, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

        self.username = wx.TextCtrl(self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.Size(150, -1), 0)  # 用户名文本框
        fgSizer6.Add(self.username, 0, wx.TOP | wx.BOTTOM | wx.LEFT, 5)

        self.password_text = wx.StaticText(self, wx.ID_ANY, u"密码:", wx.DefaultPosition, wx.Size(100, -1), 0)  # 密码标签
        self.password_text.Wrap(-1)
        self.password_text.SetFont(wx.Font(16, 70, 90, 90, False, "黑体"))
        self.password_text.SetForegroundColour(wx.Colour(180, 89, 219))

        fgSizer6.Add(self.password_text, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

        self.password = wx.TextCtrl(self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.Size(150, -1),
                                    wx.TE_PASSWORD)  # 密码文本框
        fgSizer6.Add(self.password, 0, wx.ALL, 5)

        self.login = wx.Button(self, wx.ID_ANY, u"登录", wx.DefaultPosition, wx.Size(80, -1), wx.NO_BORDER)  # 登陆按钮
        self.login.SetFont(wx.Font(12, 75, 90, 90, False, "黑体"))
        self.login.SetBackgroundColour(wx.Colour(170, 255, 170))
        self.login.SetForegroundColour(wx.Colour(255, 94, 94))

        fgSizer6.Add(self.login, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

        self.register = wx.Button(self, wx.ID_ANY, u"注册", wx.DefaultPosition, wx.Size(80, -1), wx.NO_BORDER)  # 注册按钮
        self.register.SetFont(wx.Font(12, 75, 90, 90, False, "黑体"))
        self.register.SetBackgroundColour(wx.Colour(170, 255, 170))
        self.register.SetForegroundColour(wx.Colour(128, 128, 255))

        fgSizer6.Add(self.register, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)

        self.SetSizer(fgSizer6)
        self.Layout()

        self.Centre(wx.BOTH)

        # Connect Events
        self.login.Bind(wx.EVT_BUTTON, self.loginFunc)  # 登陆按钮监听
        self.register.Bind(wx.EVT_BUTTON, self.registerFunc)  # 注册按钮监听

    def __del__(self):
        pass

    # Virtual event handlers, overide them in your derived class
    def loginFunc(self, event):  # 登录
        try:
            conn = pymysql.connect(host='localhost', user='root', password='970922', db='mytest')
            cur = conn.cursor()
        except:
            wx.MessageBox('数据库连接错误')
            return

        username = self.username.GetValue()
        password = self.password.GetValue()
        if username == "" and password == "":
            wx.MessageBox('用户名密码不能为空', caption="错误提示")
            return

        try:
            sql = 'select * from pyuser where user_name="%s"' % username
            cur.execute(sql)
            conn.commit()
        except:
            wx.MessageBox('系统错误', caption="错误提示")

        user = cur.fetchone()
        if user is None:
            wx.MessageBox('用户不存在', caption="错误提示")
            self.username.Clear()
            self.password.Clear()
            return

        if username == user[0] and password == user[1]:
            wx.MessageBox("登陆成功", caption="登陆成功")
            spiderClient = Sprider_movie.KuroNeko_Spider_GUI.SpiderClient(None)
            self.Show(False)
            spiderClient.Show(True)
        else:
            wx.MessageBox('用户名或者密码错误', caption="错误提示")
            self.username.Clear()
            self.password.Clear()
            return

    def registerFunc(self, event):  # 注册
        try:
            conn = pymysql.connect(host='localhost', user='root', password='970922', db='mytest', port=3306,
                                   charset='utf8')
            cur = conn.cursor()
        except:
            wx.MessageBox('数据库连接错误')
            return

        username = self.username.GetValue()
        password = self.password.GetValue()
        if username == "" and password == "":
            wx.MessageBox('用户名密码不能为空', caption="错误提示")
            return

        sql = 'insert into pyuser values("%s","%s")' % (username, password)
        try:
            cur.execute(sql)
            conn.commit()
            wx.MessageBox('注册成功')
            self.username.Clear()
            self.password.Clear()
        except:
            conn.rollback()
            wx.MessageBox('用户名已经存在')
            self.username.Clear()
            self.password.Clear()


if __name__ == '__main__':
    app = wx.App()
    LoginFrame = loginFrame(None)
    LoginFrame.Show()
    app.MainLoop()
