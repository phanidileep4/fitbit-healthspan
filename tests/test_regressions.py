import base64
import json
import os
import unittest
from datetime import datetime, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import fitbit_client as client
import healthspan_engine as engine
from app import LocalHandler
from session_codec import encode_session_cookie, decode_session, COOKIE_NAME


class DataTests(unittest.TestCase):
    def test_nested_dates_and_offsets(self):
        self.assertEqual(client._extract_date({'dailyRestingHeartRate':{'date':{'year':2026,'month':11,'day':10}}}), '2026-11-10')
        self.assertEqual(client._extract_date({'civilStartTime':{'date':{'year':2026,'month':11,'day':10}}}), '2026-11-10')
        self.assertEqual(client._extract_date({'bodyFat':{'sampleTime':{'physicalTime':'2026-11-11T02:00:00Z','utcOffset':'-21600s'}}}), '2026-11-10')

    def test_rollup_windows_are_closed_open_and_bounded(self):
        requests = []
        def api(method, path, token, body):
            requests.append(body)
            return {'rollupDataPoints':[]}
        with patch.object(client, '_api_request', side_effect=api):
            client._daily_rollup('steps', datetime(2026,5,1), datetime(2026,10,28), 'mock')
        self.assertEqual(len(requests),2)
        self.assertEqual(requests[0]['range']['end'],requests[1]['range']['start'])
        self.assertEqual(requests[-1]['range']['end']['date'],{'year':2026,'month':10,'day':28})
        self.assertNotIn('time',requests[0]['range']['start'])

    def test_pagination_has_filters_and_real_sleep_page_limit(self):
        paths = []
        def api(method,path,token):
            paths.append(path)
            return {'dataPoints':[{'sleep':{}}], **({'nextPageToken':'second'} if len(paths)==1 else {})}
        with patch.object(client,'_api_request',side_effect=api):
            result=client._list_points('sleep','sleep.interval.civil_end_time','2026-05-01','2026-11-01','mock')
        self.assertEqual(len(result),2)
        self.assertEqual(parse_qs(urlparse(paths[1]).query)['pageToken'],['second'])
        self.assertEqual(parse_qs(urlparse(paths[0]).query)['pageSize'],['25'])
        self.assertIn('filter',parse_qs(urlparse(paths[0]).query))

    def test_real_schema_normalization_and_failed_source(self):
        day=(datetime.now().date()-timedelta(days=2))
        date={'year':day.year,'month':day.month,'day':day.day}
        ds=day.isoformat()
        def api(method,path,token,body=None):
            if '/profile' in path: return {'age':35}
            if '/steps/' in path: return {'rollupDataPoints':[{'civilStartTime':{'date':date},'steps':{'countSum':'0'}}]}
            if '/time-in-heart-rate-zone/' in path: return {'rollupDataPoints':[{'civilStartTime':{'date':date},'timeInHeartRateZone':{'timeInHeartRateZones':[{'heartRateZone':'MODERATE','duration':'1800s'},{'heartRateZone':'PEAK','duration':'600s'}]}}]}
            if '/daily-resting-heart-rate/' in path: return {'dataPoints':[{'dailyRestingHeartRate':{'date':date,'beatsPerMinute':'57'}}]}
            if '/daily-vo2-max/' in path: return {'dataPoints':[{'dailyVo2Max':{'date':date,'vo2Max':48}}]}
            if '/body-fat/' in path: raise RuntimeError('Google Health request failed (HTTP 403).')
            if '/exercise/' in path: return {'dataPoints':[{'exercise':{'interval':{'startTime':ds+'T20:00:00Z','endTime':ds+'T21:00:00Z','startUtcOffset':'-21600s'},'exerciseType':'WEIGHTS'}}]}
            if '/sleep/' in path: return {'dataPoints':[
                {'sleep':{'interval':{'startTime':ds+'T04:00:00Z','endTime':ds+'T12:00:00Z','startUtcOffset':'-21600s','endUtcOffset':'-21600s'},'metadata':{'mainSleep':True},'summary':{'minutesAsleep':'420'}}},
                {'sleep':{'interval':{'startTime':ds+'T15:00:00Z','endTime':ds+'T16:00:00Z'},'metadata':{'nap':True},'summary':{'minutesAsleep':'55'}}}]}
            raise AssertionError(path)
        with patch.object(client,'_get_valid_access_token',return_value=('mock',{})), patch.object(client,'_api_request',side_effect=api):
            raw,age,state=client.sync_fitbit_data({})
        self.assertEqual(age,35)
        self.assertEqual(raw['heart'][0]['value']['restingHeartRate'],57)
        self.assertEqual(raw['heart'][0]['value']['heartRateZones'][0]['minutes'],30)
        self.assertEqual(raw['sleep'][0]['minutesAsleep'],420)
        self.assertIn('T22:00:00-06:00',raw['sleep'][0]['startTime'])
        self.assertEqual(len(raw['sleep']),1)
        self.assertEqual(raw['cardioscore'][0]['value']['vo2Max'],48)
        self.assertEqual(next(d for d in raw['diagnostics'] if d['metric']=='body_fat')['status'],'error')

    def test_empty_history_is_not_zero_training_or_age(self):
        data=engine.compute_from_fitbit_raw({'activities':[]},35)
        self.assertIsNone(data['biological_age'])
        self.assertIsNone(data['pace_of_aging'])
        self.assertIsNone(data['overall_score'])
        self.assertEqual(data['active_pillar_count'],0)
        self.assertEqual(data['bio_trend'],[])
        for pillar in data['pillars']:
            self.assertEqual(pillar['status'],'no_data')
            self.assertIsNone(pillar['score_0_100'])

    def test_zero_steps_count_but_today_does_not(self):
        rows=[{'dateTime':f'2026-11-{d:02}','value':'0'} for d in range(1,15)]
        rows.append({'dateTime':'2026-11-15','value':'100000'})
        data=engine.compute_from_fitbit_raw({'steps':rows,'as_of':'2026-11-15'},35)
        pillar=next(p for p in data['pillars'] if p['id']=='daily_steps')
        self.assertEqual(pillar['baseline_value'],0)
        self.assertEqual(pillar['baseline_days'],14)
        self.assertIsNone(data['biological_age'])

    def test_circular_sleep_near_midnight(self):
        logs=[{'startTime':f'2026-11-0{i}T{bed}:00','endTime':f'2026-11-0{i+1}T{wake}:00'} for i,bed,wake in [(1,'23:55','23:55'),(2,'00:05','00:05'),(3,'00:00','00:00')]]
        consistency,_=engine.compute_sleep_consistency(logs)
        self.assertGreater(consistency,95)

    def test_generic_workout_is_not_strength(self):
        raw={'as_of':'2026-11-15','activities':[{'startTime':'2026-11-10T12:00:00','activityName':'CARDIO_WORKOUT'}]}
        data=engine.compute_from_fitbit_raw(raw,35)
        pillar=next(p for p in data['pillars'] if p['id']=='strength_training')
        self.assertEqual(pillar['baseline_value'],0)

    def test_rhr_without_zones_does_not_imply_zero_cardio(self):
        raw={'as_of':'2026-11-15','heart':[{'dateTime':f'2026-11-{d:02}','value':{'restingHeartRate':58}} for d in range(1,15)]}
        data=engine.compute_from_fitbit_raw(raw,35)
        self.assertIsNone(next(p for p in data['pillars'] if p['id']=='hr_zones_1_3')['baseline_value'])

    def test_reference_guidance_and_calendars(self):
        data=engine.generate_sample_dashboard(35)
        by_id={p['id']:p for p in data['pillars']}
        self.assertEqual(len(by_id['daily_steps']['calendar']),30)
        self.assertTrue(all(d['recorded'] for d in by_id['daily_steps']['calendar']))
        self.assertIn('60–100',by_id['resting_heart_rate']['reference']['label'])
        self.assertIn('No universal',by_id['lean_body_mass']['reference']['label'])
        self.assertIn('OR',by_id['hr_zones_4_5']['reference']['label'])
        self.assertIsNotNone(data['goal_metrics']['cardio_minutes'])

    def test_manual_lean_is_undated_and_not_muscle(self):
        data=engine.compute_from_fitbit_raw({'as_of':'2026-11-15'},35,80)
        lean=next(p for p in data['pillars'] if p['id']=='lean_body_mass')
        self.assertEqual(lean['recent_value'],80)
        self.assertEqual(lean['recent_source'],'Manual fallback (undated)')
        self.assertFalse(any(d['recorded'] for d in lean['calendar']))
        self.assertIsNone(lean['latest_observation'])

    def test_one_zone_does_not_invent_other_zone_observations(self):
        raw={'as_of':'2026-11-15','heart':[{'dateTime':f'2026-11-{d:02}','value':{'heartRateZones':[{'name':'Fat Burn','minutes':30}]}} for d in range(1,15)]}
        data=engine.compute_from_fitbit_raw(raw,35)
        vigorous=next(p for p in data['pillars'] if p['id']=='hr_zones_4_5')
        self.assertIsNone(vigorous['baseline_value'])
        self.assertIsNone(data['goal_metrics']['cardio_minutes'])

    def test_strength_goal_uses_days_not_session_count(self):
        raw={'as_of':'2026-11-15','activities':[{'startTime':'2026-11-10T12:00:00','activityName':'WEIGHTS'},{'startTime':'2026-11-10T18:00:00','activityName':'WEIGHTS'}]}
        data=engine.compute_from_fitbit_raw(raw,35)
        self.assertAlmostEqual(data['goal_metrics']['strength_days'],round(7/30,2))

    def test_provider_fitness_classification_is_retained(self):
        raw={'as_of':'2026-11-15','cardioscore':[{'dateTime':'2026-11-10','value':{'vo2Max':42},'fitness_level':'GOOD'}]}
        data=engine.compute_from_fitbit_raw(raw,35)
        self.assertEqual(next(p for p in data['pillars'] if p['id']=='vo2_max')['provider_fitness_level'],'GOOD')


class SecurityTests(unittest.TestCase):
    def test_session_roundtrip_tampering_and_legacy(self):
        state={'tokens':{'access_token':'not-a-real-token'},'chronological_age':35}
        cookie=encode_session_cookie(state,True)
        self.assertNotIn('not-a-real-token',cookie)
        self.assertEqual(decode_session(cookie),state)
        value=cookie.split(';')[0].split('=',1)[1]
        self.assertEqual(decode_session(f'{COOKIE_NAME}='+value[:-5]+'abcde'),{})
        legacy=base64.urlsafe_b64encode(json.dumps(state).encode()).decode()
        self.assertEqual(decode_session('gh_session='+legacy),{})
        self.assertIn('Secure',cookie)
        self.assertIn('HttpOnly',cookie)

    def test_invalid_profiles(self):
        for age in [0,101,float('nan'),float('inf')]:
            with self.assertRaises(ValueError): client.update_config({},chronological_age=age)
        for lean in [-1,99,float('nan')]:
            with self.assertRaises(ValueError): client.update_config({},manual_lean_pct=lean)

    def test_oauth_state_and_expiration(self):
        with self.assertRaises(RuntimeError): client.exchange_code({'pkce':{'state':'x','created_at':0}},'fake','x','http://localhost/callback')


class HTTPTests(unittest.TestCase):
    def request(self,path,body=None,headers=None):
        # Exercise the real handler without needing a listening socket.
        import io
        from email.message import Message
        handler=LocalHandler.__new__(LocalHandler)
        handler.command='GET' if body is None else 'POST'
        handler.path=path
        handler.request_version='HTTP/1.1'
        handler.requestline=f'{handler.command} {path} HTTP/1.1'
        handler.client_address=('127.0.0.1',0)
        handler.headers=Message()
        handler.headers['Host']='localhost:8765'
        for key,value in (headers or {}).items(): handler.headers[key]=value
        encoded=(body or '').encode()
        handler.headers['Content-Length']=str(len(encoded))
        handler.rfile=io.BytesIO(encoded)
        handler.wfile=io.BytesIO()
        getattr(handler,'do_'+handler.command)()
        head,content=handler.wfile.getvalue().split(b'\r\n\r\n',1)
        lines=head.decode().split('\r\n')
        status=int(lines[0].split()[1])
        return status,dict(line.split(': ',1) for line in lines[1:]),content
    def test_routes_and_headers(self):
        for path in ['/','/privacy','/methodology','/api/dashboard']:
            status,headers,body=self.request(path)
            self.assertEqual(status,200)
            self.assertEqual(headers['Cache-Control'],'no-store')
        data=json.loads(self.request('/api/dashboard')[2]);self.assertEqual(data['data_source'],'sample_preview')
    def test_bad_input_and_csrf(self):
        self.assertEqual(self.request('/api/config','[]')[0],400)
        self.assertEqual(self.request('/api/config','{"chronological_age":-1}')[0],400)
        self.assertEqual(self.request('/api/config','{}',{'Origin':'https://evil.example'})[0],403)
    def test_callback_html_escaped(self):
        status,headers,body=self.request('/callback?error=%3Cscript%3Ealert(1)%3C/script%3E')
        self.assertEqual(status,400)
        self.assertNotIn(b'<script>',body)
        self.assertIn(b'&lt;script&gt;',body)

if __name__=='__main__': unittest.main()
