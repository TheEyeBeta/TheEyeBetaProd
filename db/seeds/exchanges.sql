INSERT INTO theeyebeta.exchanges (code, name, country_iso2, timezone, currency_iso) VALUES
('XNAS', 'NASDAQ', 'US', 'America/New_York', 'USD'),
('XNYS', 'New York Stock Exchange', 'US', 'America/New_York', 'USD'),
('XSHG', 'Shanghai Stock Exchange', 'CN', 'Asia/Shanghai', 'CNY'),
('XSHE', 'Shenzhen Stock Exchange', 'CN', 'Asia/Shanghai', 'CNY'),
('XTAI', 'Taiwan Stock Exchange', 'TW', 'Asia/Taipei', 'TWD'),
('XTKS', 'Tokyo Stock Exchange', 'JP', 'Asia/Tokyo', 'JPY'),
('XHKG', 'Hong Kong Exchange', 'HK', 'Asia/Hong_Kong', 'HKD')
ON CONFLICT (code) DO NOTHING;
