"""Consultas agregadas sobre ocupacion, incidentes y sesiones."""

def _time(value):
    """Convierte fechas u otros valores al formato textual de las consultas."""
    return value.isoformat(timespec="seconds") if hasattr(value, "isoformat") else str(value)


class Analytics:
    """Agrupa las consultas de negocio sin exponer detalles de SQLite."""
    def __init__(self, repository):
        """Recibe el repositorio que ejecutara todas las consultas."""
        self.repository = repository

    def understaffed_by_hour(self, zone, start, end):
        """Calcula por hora el porcentaje debajo del minimo en una zona."""
        return self.repository.query("""SELECT strftime('%H:00',sampled_at) hour,
          ROUND(100.0*SUM(status='missing')/COUNT(*),1) missing_percent,
          ROUND(AVG(people_count),2) avg_occupancy,COUNT(*) samples
          FROM occupancy_samples WHERE zone=? AND sampled_at>=? AND sampled_at<?
          GROUP BY strftime('%H',sampled_at) ORDER BY hour""", (zone,_time(start),_time(end)))

    def minutes_below_minimum(self, zone, start, end):
        """Estima minutos de faltantes usando el intervalo entre muestras."""
        return self.repository.query("""WITH ordered AS (SELECT sampled_at,status,
          LEAD(sampled_at,1,?) OVER(PARTITION BY camera_id ORDER BY sampled_at) next_at
          FROM occupancy_samples WHERE zone=? AND sampled_at>=? AND sampled_at<?)
          SELECT ROUND(COALESCE(SUM(CASE WHEN status='missing' THEN
          (julianday(next_at)-julianday(sampled_at))*1440 ELSE 0 END),0),2) minutes FROM ordered""",
          (_time(end),zone,_time(start),_time(end)))[0]

    def employee_time_by_zone(self, start, end, employee_id=None):
        """Suma sesiones por empleado y zona dentro del periodo consultado."""
        where = "AND employee_id=?" if employee_id else ""
        params = [_time(end),_time(end),_time(start),_time(end),_time(end),_time(start)] + ([employee_id] if employee_id else [])
        return self.repository.query(f"""SELECT employee_id,zone,
          ROUND(SUM((julianday(MIN(COALESCE(exited_at,?),?))-julianday(MAX(entered_at,?)))*86400),1) seconds
          FROM zone_sessions WHERE entered_at<? AND COALESCE(exited_at,?)>? {where}
          GROUP BY employee_id,zone ORDER BY employee_id,seconds DESC""", tuple(params))

    def common_transitions(self, start, end, limit=20):
        """Ordena las transiciones entre zonas por frecuencia."""
        return self.repository.query("""SELECT from_zone,to_zone,COUNT(*) transitions FROM zone_transitions
          WHERE transitioned_at>=? AND transitioned_at<? GROUP BY from_zone,to_zone
          ORDER BY transitions DESC LIMIT ?""", (_time(start),_time(end),int(limit)))

    def long_incidents(self, start, end, minutes=20):
        """Cuenta incidentes que superan una duracion minima."""
        return self.repository.query("""SELECT COUNT(*) incidents FROM incidents WHERE started_at>=? AND started_at<?
          AND COALESCE(duration_seconds,(julianday(?)-julianday(started_at))*86400)>?""",
          (_time(start),_time(end),_time(end),float(minutes)*60))[0]

    def false_positives_by_camera(self, start, end, minimum_reviews=1):
        """Calcula la tasa revisada de falsos positivos por camara."""
        return self.repository.query("""SELECT camera_id,SUM(is_false_positive) false_positives,COUNT(*) reviewed,
          ROUND(100.0*SUM(is_false_positive)/COUNT(*),1) false_positive_rate FROM detection_reviews
          WHERE detection_at>=? AND detection_at<? GROUP BY camera_id HAVING COUNT(*)>=?
          ORDER BY false_positive_rate DESC,reviewed DESC""", (_time(start),_time(end),int(minimum_reviews)))

    def average_occupancy_by_hour(self, start, end, zone=None):
        """Resume ocupacion minima, maxima y promedio por zona y hora."""
        where = "AND zone=?" if zone else ""
        params = [_time(start),_time(end)] + ([zone] if zone else [])
        return self.repository.query(f"""SELECT zone,strftime('%H:00',sampled_at) hour,
          ROUND(AVG(people_count),2) avg_occupancy,MIN(people_count) min_occupancy,
          MAX(people_count) max_occupancy,COUNT(*) samples FROM occupancy_samples
          WHERE sampled_at>=? AND sampled_at<? {where} GROUP BY zone,strftime('%H',sampled_at)
          ORDER BY zone,hour""", tuple(params))
