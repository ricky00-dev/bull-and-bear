"""Bounded HTTPS transport for the same chart feed used by pykrx's stock prices.

This unofficial feed is isolated from the default KRX market-data path.
"""
from datetime import datetime
from xml.etree import ElementTree

import httpx

from .base import DataUnavailable, PriceBar
from .pykrx_dart import PykrxDartSource


def chart_rows(symbol, count):
    try:
        response = httpx.get('https://fchart.stock.naver.com/sise.nhn', timeout=6,
                             params={'symbol': symbol, 'timeframe': 'day', 'count': count, 'requestType': 0})
        response.raise_for_status()
        root = ElementTree.fromstring(response.content.decode('euc-kr'))
        rows = [item.attrib['data'].split('|') for item in root.iter('item')]
        if not rows:
            raise ValueError('empty chart')
        return rows
    except (httpx.HTTPError, ValueError, KeyError, ElementTree.ParseError) as exc:
        raise DataUnavailable('시세 공급자 응답을 읽을 수 없습니다') from exc


class HttpMarketSource(PykrxDartSource):
    name = 'naver-chart+opendart'

    def get_daily_prices(self, ticker, start, end):
        from ..snapshot import KST
        count = (datetime.now(KST).date() - start).days + 10
        if count > 10000:
            raise DataUnavailable('시세 조회 구간이 너무 깁니다')
        bars = []
        try:
            for row in chart_rows(ticker, count):
                day = datetime.strptime(row[0], '%Y%m%d').date()
                if start <= day <= end:
                    o, h, low, close = map(float, row[1:5])
                    volume = int(row[5])
                    if o == 0 and volume == 0:
                        continue
                    bars.append(PriceBar(day, o, h, low, close, volume))
        except (ValueError, IndexError) as exc:
            raise DataUnavailable('시세 형식 오류') from exc
        return sorted(bars, key=lambda bar: bar.date)
