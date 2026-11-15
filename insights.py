"""Recorded coverage and sourced comparison guidance; never clinical age validation."""
from datetime import date, timedelta

SOURCES = {
    'sleep': ('NIH: adult sleep', 'https://www.nhlbi.nih.gov/health/sleep/how-much-sleep'),
    'regularity': ('NIH: healthy sleep habits', 'https://www.nhlbi.nih.gov/health/sleep-deprivation/healthy-sleep-habits'),
    'activity': ('CDC: adult activity guidance', 'https://www.cdc.gov/physical-activity-basics/guidelines/adults.html'),
    'steps': ('NIH: observational step-count research', 'https://www.nih.gov/news-events/nih-research-matters/number-steps-day-more-important-step-intensity'),
    'rhr': ('American Heart Association: resting heart rate', 'https://www.heart.org/en/healthy-living/exercise-and-physical-activity/fitness-basics/target-heart-rates/'),
    'vo2': ('Google Health: interpreting VO2 max', 'https://support.google.com/googlehealth/answer/14237924'),
}


def enrich_dashboard(result, raw, manual_lean_pct=None):
    end = date.fromisoformat(result['window']['end_exclusive'])
    begin = end - timedelta(days=30)
    keys = ['sleep', 'steps', 'moderate', 'vigorous', 'strength', 'rhr', 'vo2', 'lean']
    days = {k: set() for k in keys}
    for row in raw.get('steps', []):
        if row.get('value') is not None: days['steps'].add(row.get('dateTime', ''))
    for row in raw.get('sleep', []):
        if row.get('isMainSleep', True) and (row.get('minutesAsleep') or 0) > 0:
            days['sleep'].add(row.get('dateOfSleep', ''))
    for row in raw.get('heart', []):
        d, value = row.get('dateTime', ''), row.get('value', {})
        if value.get('restingHeartRate') is not None: days['rhr'].add(d)
        zones = value.get('heartRateZones')
        if zones is not None:
            # Explicit provider zone observations, including true zero durations.
            if any(z.get('name') == 'Fat Burn' for z in zones): days['moderate'].add(d)
            if any(z.get('name') in ('Cardio', 'Peak') for z in zones): days['vigorous'].add(d)
    for row in raw.get('cardioscore', []): days['vo2'].add(row.get('dateTime', ''))
    for row in raw.get('body_fat', []):
        if row.get('fat') is not None: days['lean'].add(row.get('date', ''))
    strength_types = {'weights','strength_training','functional_strength_training','free_weights','weightlifting',
                      'weight_machines','powerlifting','resistance_bands','body_weight','calisthenics','strength'}
    training = set()
    for row in raw.get('activities', []):
        d = (row.get('startTime') or '')[:10]
        days['strength'].add(d)
        if (row.get('activityName') or '').lower().replace(' ', '_') in strength_types: training.add(d)
    mapping = {'sleep_consistency':'sleep','sleep_duration':'sleep','daily_steps':'steps',
               'hr_zones_1_3':'moderate','hr_zones_4_5':'vigorous','strength_training':'strength',
               'resting_heart_rate':'rhr','vo2_max':'vo2','lean_body_mass':'lean'}
    guidance = {
        'sleep_consistency': ('Keep sleep/wake times consistent', 'This percentage is an app-defined regularity measure, with no validated healthy cutoff.', 'regularity'),
        'sleep_duration': ('7–9 hours/night (general adult guidance)', 'Sleep needs vary. The app shows main sleep, while general sleep recommendations include total daily sleep.', 'sleep'),
        'daily_steps': ('Increase from your baseline; set a personal goal', 'No universal 10,000-step requirement. Research linking 8,000+ steps to lower mortality is observational and included adults 40+; it is not a personal risk prediction.', 'steps'),
        'hr_zones_1_3': ('150 moderate-equivalent minutes/week', 'Moderate minutes + 2 × vigorous minutes count toward one combined target; you do not need both 150 moderate AND 75 vigorous. Device zones are approximate.', 'activity'),
        'hr_zones_4_5': ('75 vigorous OR 150 moderate minutes/week', 'An equivalent combination also counts. This is activity guidance, not a separate mandatory vigorous quota.', 'activity'),
        'strength_training': ('2+ distinct strength-training days/week', 'Guidance is days, not sessions, and covers all major muscle groups. Unlogged training cannot be inferred from an empty history.', 'activity'),
        'resting_heart_rate': ('Typically 60–100 bpm in adults', 'Active people can be below 60. Medication, symptoms, and your usual baseline matter; lower is not always better.', 'rhr'),
        'vo2_max': ('Use age/sex-adjusted provider classification', 'A single 45 mL/kg/min target is not appropriate for everyone. Google interprets VO2 max using demographic context.', 'vo2'),
        'lean_body_mass': ('No universal healthy lean-mass percentage', 'Lean mass = 100 − body fat %. It includes water, organs, bone, and muscle; it is not muscle percentage. Reference ranges depend on age, sex, and measurement method.', None),
    }
    for p in result['pillars']:
        key = mapping[p['id']]
        observed = sorted(d for d in days[key] if result['window']['start'] <= d < end.isoformat())
        recent = [d for d in observed if d >= begin.isoformat()]
        p['observation_days'] = len(observed)
        p['calendar'] = [{'date': (begin + timedelta(days=i)).isoformat(),
                          'recorded': (begin + timedelta(days=i)).isoformat() in days[key]} for i in range(30)]
        p['latest_observation'] = observed[-1] if observed else None
        p['days_since_observation'] = (end - date.fromisoformat(observed[-1])).days if observed else None
        p['freshness'] = 'No dated observations' if not observed else (
            'Within last 7 days' if p['days_since_observation'] <= 7 else f"Last observation {p['days_since_observation']} days ago")
        p['coverage_note'] = 'Recorded exercise days; missing days do not prove no training.' if key == 'strength' else 'Recorded days; gaps are not zero values.'
        label, note, source = guidance[p['id']]
        p['reference'] = {'label': label, 'note': note, 'source_label': SOURCES[source][0] if source else None,
                          'source_url': SOURCES[source][1] if source else None}
        p['target_label'] = label
        if key == 'lean':
            baseline_auto = bool(observed)
            recent_auto = bool(recent)
            p['baseline_source'] = 'Body-fat logs (100 − body fat %)' if baseline_auto else ('Manual fallback (undated)' if manual_lean_pct is not None else 'Unavailable')
            p['recent_source'] = 'Body-fat logs (100 − body fat %)' if recent_auto else ('Manual fallback (undated)' if manual_lean_pct is not None else 'Unavailable')
            if manual_lean_pct is not None and not baseline_auto: p['freshness'] = 'Manual entry; no measurement date supplied'
        if key == 'vo2':
            rows = [r for r in raw.get('cardioscore', []) if begin.isoformat() <= r.get('dateTime', '') < end.isoformat()]
            latest = max(rows, key=lambda r: r['dateTime'], default={})
            p['provider_fitness_level'] = latest.get('fitness_level')
    result['goal_metrics'] = {
        'sleep_hours': next(p['recent_value'] for p in result['pillars'] if p['id']=='sleep_duration'),
        'steps': next(p['recent_value'] for p in result['pillars'] if p['id']=='daily_steps'),
        'strength_days': round(sum(begin.isoformat() <= d < end.isoformat() for d in training) / (30/7), 2) if any(begin.isoformat() <= d < end.isoformat() for d in days['strength']) else None,
    }
    by_id = {p['id']: p for p in result['pillars']}
    moderate, vigorous = by_id['hr_zones_1_3']['recent_value'], by_id['hr_zones_4_5']['recent_value']
    # Compare combined activity only when both components cover exactly the same recent dates.
    zone_days_match = {d for d in days['moderate'] if begin.isoformat() <= d < end.isoformat()} == {d for d in days['vigorous'] if begin.isoformat() <= d < end.isoformat()}
    result['goal_metrics']['cardio_minutes'] = round(moderate + 2*vigorous) if moderate is not None and vigorous is not None and zone_days_match else None
    result['guidance_version'] = 'adult-reference-2026-11'
    return result
