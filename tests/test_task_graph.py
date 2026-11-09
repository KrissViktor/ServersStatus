import json
import unittest
from server.task_graph import graph
from server.overview import compact_card
from server.dashboard import server_card

class TaskGraphTest(unittest.TestCase):
    def test_grid_line_fill_and_gaps(self):
        points=[{'timestamp':720,'cpu':10},{'timestamp':730,'cpu':50},{'timestamp':800,'cpu':80}]
        markup=graph(points,'cpu',1000)
        self.assertEqual(markup.count('class="task-line"'),2)
        self.assertEqual(markup.count('class="task-fill"'),1)
        self.assertEqual(markup.count('class="task-point"'),3)
        self.assertIn('50.0%',markup)
        self.assertNotIn('task-empty',markup)
        self.assertIn('Нет измерений',graph([],'cpu',1000))
        legacy=[{'timestamp':t,'cpu':20} for t in (720,780,840)]
        self.assertEqual(graph(legacy,'cpu',1000).count('class="task-line"'),1)

    def test_both_cards_use_charts_and_keep_values(self):
        row={'id':'pc','received':1000,'data':json.dumps({'hostname':'PC','cpu_percent':25,'memory_percent':50,
             'system':{'cpu_current_mhz':3200,'memory_total_bytes':16*1024**3,'memory_used_bytes':8*1024**3},'disks':[]}),
             'sparkline':[{'timestamp':990,'cpu':20,'ram':45},{'timestamp':1000,'cpu':25,'ram':50}]}
        for markup in (compact_card(row,1000),server_card(row,1000)):
            self.assertEqual(markup.count('class="task-graph"'),2)
            self.assertNotIn('<progress',markup)
            self.assertIn('8.0 Гб / 16.0 Гб',markup)
            self.assertIn('3.20 ГГц',markup)
            self.assertIn('5 минут',markup)

    def test_missing_logical_cpu_sample_is_a_gap(self):
        points=[{'timestamp':980,'cpu':10},{'timestamp':990,'cpu':None},{'timestamp':1000,'cpu':80}]
        markup=graph(points,'cpu',1000,core=2)
        self.assertEqual(markup.count('class="task-line"'),2)
        self.assertIn('Логический процессор 2',markup)
        self.assertIn('data-detail-name="2"',markup)
