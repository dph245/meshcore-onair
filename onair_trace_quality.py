"""Statistics and configurable reference values for observed TRACE links."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import floor
from statistics import median

from onair_observer_radio import CORE_FIELDS

DAY = 86400
RULES = dict(
    demodulation_db={5: -2.5, 6: -5, 7: -7.5, 8: -10, 9: -12.5, 10: -15, 11: -17.5, 12: -20},
    reserve_good_db=6, reserve_watch_db=3, median_min=3, p10_min=10,
    asymmetry_good_db=3, asymmetry_watch_db=6, asymmetry_window_hours=1,
    asymmetry_windows_min=2, asymmetry_min=3, asymmetry_max_ratio=3,
    coverage_good=dict(count=10, days=3, span_hours=48, age_days=7, assigned=.8),
    coverage_watch=dict(count=3, days=2, span_hours=24, age_days=30, assigned=.5),
)


def complete(profile):
    return all(field in profile for field in CORE_FIELDS)


def percentiles(histogram, count, probabilities):
    """Linear interpolation at zero-based rank (n - 1) × p on quarter-dB integers."""
    values = sorted(histogram.items())
    result = []
    index = 0
    value, cumulative = values[index]
    for probability in probabilities:
        rank = (count - 1) * probability
        lower = floor(rank)
        while cumulative <= lower:
            index += 1
            value = values[index][0]
            cumulative += values[index][1]
        upper = values[index + 1][0] if lower + 1 == cumulative and rank > lower else value
        result.append(round((value + (upper - value) * (rank - lower)) / 4, 6))
    return result


@dataclass
class DirectionSamples:
    # At most one representative per correlated TRACE in this direction/profile.
    readings: dict = field(default_factory=dict)

    def add(self, stamp, identity, hop, snr, quality):
        reading = snr, stamp, hop, quality
        previous = self.readings.get(identity)
        if previous is None or reading < previous:
            self.readings[identity] = reading

    def result(self):
        readings = self.readings.values()
        count = len(readings)
        histogram = Counter(reading[0] for reading in readings)
        minimum, p10, middle, p90, maximum = percentiles(histogram, count, (0, .1, .5, .9, 1))
        _, last = max(self.readings.items(), key=lambda entry: (entry[1][1], entry[0], entry[1][2]))
        return dict(count=count, last=last[0] / 4, min=minimum, p10=p10, median=middle, p90=p90, max=maximum,
                    first_at=min(r[1] for r in readings), last_at=last[1], quality=dict(Counter(r[3] for r in readings)))

    def windows(self):
        bins = defaultdict(list)
        for snr, stamp, _, _ in self.readings.values():
            bins[int(stamp // (RULES['asymmetry_window_hours'] * 3600))].append(snr)
        return bins


def reserve_category(value):
    if value >= RULES['reserve_good_db']:
        return 'good'
    return 'watch' if value >= RULES['reserve_watch_db'] else 'low'


def reserve(values, reference):
    if not values or reference is None or values['count'] < RULES['median_min']:
        return None
    statistic = 'p10' if values['count'] >= RULES['p10_min'] else 'median'
    return dict(db=round(values[statistic] - reference, 6), statistic=statistic, reference_db=reference)


def asymmetry_category(delta):
    if delta <= RULES['asymmetry_good_db']:
        return 'good'
    return 'watch' if delta <= RULES['asymmetry_watch_db'] else 'low'


def asymmetry(directions):
    forward, reverse = (sample.windows() for sample in directions)
    shared = forward.keys() & reverse.keys()
    comparable = [(forward[hour], reverse[hour]) for hour in shared
                  if max(len(forward[hour]), len(reverse[hour])) <=
                  RULES['asymmetry_max_ratio'] * min(len(forward[hour]), len(reverse[hour]))]
    if len(comparable) < RULES['asymmetry_windows_min']:
        return None
    counts = [sum(len(values) for values in column) for column in zip(*comparable)]
    if min(counts) < RULES['asymmetry_min']:
        return None
    # Each comparable time window has equal weight, including on busy days.
    delta = median(median(a) - median(b) for a, b in comparable) / 4
    return dict(db=abs(delta), signed_db=delta, windows=len(comparable), counts=counts)


def assess_profile(profile, directions):
    reference = RULES['demodulation_db'].get(profile.get('spreading_factor')) if complete(profile) else None
    readings = [sample.result() if sample else None for sample in directions]
    for values in filter(None, readings):
        values['reserve'] = reserve(values, reference)
        values['sf7'] = (reserve(values, RULES['demodulation_db'][7])
                         if reference is not None and profile['spreading_factor'] == 8 else None)
    comparison = (asymmetry(directions) if reference is not None and all(
        values and values['count'] >= RULES['asymmetry_min'] for values in readings) else None)
    return dict(profile=profile, forward=readings[0], reverse=readings[1], asymmetry=comparison)


def directional_coverage(profile_samples, end):
    measurements = {}
    for profile, samples in profile_samples:
        is_complete = complete(dict(profile))
        for identity, (_, stamp, _, quality) in samples.readings.items():
            assignment = quality if is_complete else 'unassigned'
            if identity in measurements:
                previous, previous_profile, previous_quality = measurements[identity]
                stamp = min(previous, stamp)
                if previous_profile != profile or previous_quality == 'mixed':
                    assignment = 'mixed'
            measurements[identity] = stamp, profile, assignment
    if not measurements:
        return None
    times = [record[0] for record in measurements.values()]
    first, last = min(times), max(times)
    quality = Counter(record[2] for record in measurements.values())
    return dict(count=len(times), days=len({int(stamp // DAY) for stamp in times}),
                span_hours=(last - first) / 3600, age_days=max(0, (end - last) / DAY),
                first_at=first, last_at=last, quality=dict(quality),
                assigned=(quality['confirmed'] + quality['last_known']) / len(times))


def _coverage_grade(direction):
    if not direction:
        return 0
    for score, category in ((3, 'good'), (2, 'watch')):
        cutoffs = RULES[f'coverage_{category}']
        if direction['age_days'] <= cutoffs['age_days'] and all(
            direction[name] >= cutoffs[name] for name in ('count', 'days', 'span_hours', 'assigned')
        ):
            return score
    return 1


def assess_link(groups, coverage):
    """Evaluate exact profiles separately and return the profile driving each mode."""
    result = {}
    for mode in ('reserve', 'sf7'):
        candidates = []
        for index, group in groups:
            directions = [(value[mode]['db'], direction) for direction in ('forward', 'reverse')
                          if (value := group[direction]) and value[mode]]
            if directions:
                value, direction = min(directions)
                candidates.append((value, index, direction, len(directions)))
        if candidates:
            value, index, direction, count = min(candidates)
            result[mode] = dict(category=reserve_category(value), db=value, profile_index=index,
                                direction=direction, directions=count)
        else:
            result[mode] = dict(category='unknown')
    comparisons = [(group['asymmetry']['db'], index) for index, group in groups if group['asymmetry'] is not None]
    if comparisons:
        value, index = max(comparisons, key=lambda item: (item[0], -item[1]))
        result['asymmetry'] = dict(category=asymmetry_category(value), db=value, profile_index=index, directions=2)
    else:
        result['asymmetry'] = dict(category='unknown')
    score = max(1, min(map(_coverage_grade, coverage.values())))
    result['coverage'] = dict(category={1: 'low', 2: 'watch', 3: 'good'}[score], score=score)
    return result
