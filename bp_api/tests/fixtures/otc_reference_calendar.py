# -*- coding: utf-8 -*-
# 金标准日历：复制自 autocallables-pricing/date_utils/calendars.py（用户提供参考实现）。
# 维护范围约 2004-2024（原注释：2022 后为推测），仅用于 OTC 金标复算测试，不参与生产。
# 生产日历使用 bp_trading_calendar。
# 节假日已维护至2022年
# 其中2022年的节假日是根据现有假日安排的猜测，并非实际
# 每年年初应当按照国家节假日的具体安排更新本代码

class China:
    def __init__(self, market=None):
        self.market = market

    @staticmethod
    def is_weekend(date):
        return date.weekday() >= 5

    @staticmethod
    def is_business_day(date):
        y = date.year
        m = date.month
        d = date.day
        if (China.is_weekend(date)
                or (d == 1 and m == 1)
                or (y == 2005 and d == 3 and m == 1)
                or (y == 2006 and (d == 2 and d == 3) and m == 1)
                or (y == 2007 and d <= 3 and m == 1)
                or (y == 2007 and d == 31 and m == 12)
                or (y == 2009 and d == 2 and m == 1)
                or (y == 2011 and d == 3 and m == 1)
                or (y == 2012 and (d == 2 or d == 3) and m == 1)
                or (y == 2013 and d <= 3 and m == 1)
                or (y == 2014 and d == 1 and m == 1)
                or (y == 2015 and d <= 3 and m == 1)
                or (y == 2017 and d == 2 and m == 1)
                or (y == 2018 and d == 1 and m == 1)
                or (y == 2018 and d == 31 and m == 12)
                or (y == 2019 and d == 1 and m == 1)
                or (y == 2020 and d == 1 and m == 1)
                or (y == 2021 and d <= 3 and m == 1)
                or (y == 2022 and d <= 3 and m == 1)
                or (y == 2022 and d == 31 and m == 12)
                or (y == 2023 and d == 2 and m == 1)
                # guess
                or (y == 2023 and d == 31 and m == 12)
                or (y == 2024 and d == 2 and m == 1)
                # Chinese New Year
                or (y == 2004 and 19 <= d <= 28 and m == 1)
                or (y == 2005 and 7 <= d <= 15 and m == 2)
                or (y == 2006 and ((d >= 26 and m == 1) or (d <= 3 and m == 2)))
                or (y == 2007 and 17 <= d <= 25 and m == 2)
                or (y == 2008 and 6 <= d <= 12 and m == 2)
                or (y == 2009 and 26 <= d <= 30 and m == 1)
                or (y == 2010 and 15 <= d <= 19 and m == 2)
                or (y == 2011 and 2 <= d <= 8 and m == 2)
                or (y == 2012 and 23 <= d <= 28 and m == 1)
                or (y == 2013 and 11 <= d <= 15 and m == 2)
                or (y == 2014 and d >= 31 and m == 1)
                or (y == 2014 and d <= 6 and m == 2)
                or (y == 2015 and 18 <= d <= 24 and m == 2)
                or (y == 2016 and 8 <= d <= 12 and m == 2)
                or (y == 2017 and ((d >= 27 and m == 1) or (d <= 2 and m == 2)))
                or (y == 2018 and (15 <= d <= 21 and m == 2))
                or (y == 2019 and 4 <= d <= 8 and m == 2)
                or (y == 2020 and (d == 24 or (27 <= d <= 31)) and m == 1)
                or (y == 2021 and (11 <= d <= 17) and m == 2)
                # guess, not real
                or (y == 2022 and (1 <= d <= 4) and m == 2)
                or (y == 2022 and d == 31 and m == 1)
                or (y == 2023 and (23 <= d <= 27) and m == 1)
                or (y == 2024 and d == 9 and m == 1)
                or (y == 2024 and (12 <= d <= 15) and m == 1)
                # QingMing Festival
                or (y <= 2008 and d == 4 and m == 4)
                or (y == 2009 and d == 6 and m == 4)
                or (y == 2010 and d == 5 and m == 4)
                or (y == 2011 and 3 <= d <= 5 and m == 4)
                or (y == 2012 and 2 <= d <= 4 and m == 4)
                or (y == 2013 and 4 <= d <= 5 and m == 4)
                or (y == 2014 and d == 7 and m == 4)
                or (y == 2015 and 5 <= d <= 6 and m == 4)
                or (y == 2016 and d == 4 and m == 4)
                or (y == 2017 and 3 <= d <= 4 and m == 4)
                or (y == 2018 and 5 <= d <= 6 and m == 4)
                or (y == 2019 and d == 5 and m == 4)
                or (y == 2020 and d == 6 and m == 4)
                or (y == 2021 and 3 <= d <= 5 and m == 4)
                # guess
                or (y == 2022 and d == 5 and m == 4)
                or (y == 2023 and d == 5 and m == 4)
                or (y == 2024 and d == 5 and m == 4)
                # Labor Day
                or (y <= 2007 and 1 <= d <= 7 and m == 5)
                or (y == 2008 and 1 <= d <= 2 and m == 5)
                or (y == 2009 and d == 1 and m == 5)
                or (y == 2010 and d == 3 and m == 5)
                or (y == 2011 and d == 2 and m == 5)
                or (y == 2012 and ((d == 30 and m == 4) or (d == 1 and m == 5)))
                or (y == 2013 and ((d >= 29 and m == 4) or (d == 1 and m == 5)))
                or (y == 2014 and 1 <= d <= 3 and m == 5)
                or (y == 2015 and d == 1 and m == 5)
                or (y == 2016 and 1 <= d <= 2 and m == 5)
                or (y == 2017 and d == 1 and m == 5)
                or (y == 2018 and ((d == 30 and m == 4) or (d == 1 and m == 5)))
                or (y == 2019 and 1 <= d <= 3 and m == 5)
                or (y == 2020 and (d == 1 or d == 4 or d == 5) and m == 5)
                or (y == 2021 and (1 <= d <= 5) and m == 5)
                or (y == 2022 and (2 <= d <= 4) and m == 5)
                or (y == 2023 and (1 <= d <= 3) and m == 5)
                or (y == 2024 and (1 <= d <= 3) and m == 5)
                # Dragon Boat Festival
                or (y <= 2008 and d == 9 and m == 6)
                or (y == 2009 and (d == 28 or d == 29) and m == 5)
                or (y == 2010 and 14 <= d <= 16 and m == 6)
                or (y == 2011 and 4 <= d <= 6 and m == 6)
                or (y == 2012 and 22 <= d <= 24 and m == 6)
                or (y == 2013 and 10 <= d <= 12 and m == 6)
                or (y == 2014 and d == 2 and m == 6)
                or (y == 2015 and d == 22 and m == 6)
                or (y == 2016 and 9 <= d <= 10 and m == 6)
                or (y == 2017 and 29 <= d <= 30 and m == 5)
                or (y == 2018 and d == 18 and m == 6)
                or (y == 2019 and d == 7 and m == 6)
                or (y == 2020 and 25 <= d <= 26 and m == 6)
                or (y == 2021 and 12 <= d <= 14 and m == 6)
                # guess
                or (y == 2022 and d == 3 and m == 6)
                or (y == 2023 and (22 <= d <= 24) and m == 6)
                or (y == 2024 and d == 10 and m == 6)
                # Mid-Autumn Festival
                or (y <= 2008 and d == 15 and m == 9)
                or (y == 2010 and 22 <= d <= 24 and m == 9)
                or (y == 2011 and 10 <= d <= 12 and m == 9)
                or (y == 2012 and d == 30 and m == 9)
                or (y == 2013 and 19 <= d <= 20 and m == 9)
                or (y == 2014 and d == 8 and m == 9)
                or (y == 2015 and d == 27 and m == 9)
                or (y == 2016 and 15 <= d <= 16 and m == 9)
                or (y == 2018 and d == 24 and m == 9)
                or (y == 2019 and d == 13 and m == 9)
                or (y == 2021 and 19 <= d <= 21 and m == 9)
                or (y == 2022 and d == 12 and m == 9)
                or (y == 2023 and d == 29 and m == 9)
                or (y == 2024 and (16 <= d <= 17) and m == 9)
                # National Day
                or (y <= 2007 and 1 <= d <= 7 and m == 10)
                or (y == 2008 and ((d >= 29 and m == 9) or (d <= 3 and m == 10)))
                or (y == 2009 and 1 <= d <= 8 and m == 10)
                or (y == 2010 and 1 <= d <= 7 and m == 10)
                or (y == 2011 and 1 <= d <= 7 and m == 10)
                or (y == 2012 and 1 <= d <= 7 and m == 10)
                or (y == 2013 and 1 <= d <= 7 and m == 10)
                or (y == 2014 and 1 <= d <= 7 and m == 10)
                or (y == 2015 and 1 <= d <= 7 and m == 10)
                or (y == 2016 and 3 <= d <= 7 and m == 10)
                or (y == 2017 and 2 <= d <= 6 and m == 10)
                or (y == 2018 and 1 <= d <= 5 and m == 10)
                or (y == 2019 and 1 <= d <= 7 and m == 10)
                or (y == 2020 and 1 <= d <= 2 and m == 10)
                or (y == 2020 and 5 <= d <= 8 and m == 10)
                or (y == 2021 and 1 <= d <= 7 and m == 10)
                or (y == 2022 and 3 <= d <= 7 and m == 10)
                or (y == 2023 and 2 <= d <= 6 and m == 10)
                or (y == 2024 and 1 <= d <= 4 and m == 10)
                # 70th anniversary of the victory of anti-Japaneses war
                or (y == 2015 and 3 <= d <= 4 and m == 9)):
            return False
        return True

    def business_days_between(self, from_date, to_date):
        number_business_days = 0.0
        if to_date != from_date:
            current_date = from_date.next_day()
            while current_date <= to_date:
                if self.is_business_day(current_date):
                    number_business_days += 1
                current_date = current_date.next_day()
        return number_business_days


