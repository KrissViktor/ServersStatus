import unittest
from server.console_output import clean_output


class ConsoleOutputTest(unittest.TestCase):
    prefix='<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
    def test_progress_removed_and_plain_output_untouched(self):
        progress=self.prefix+'<Obj S="progress" RefId="0"><TN RefId="0"><T>ProgressRecord</T></TN><ToString>Loading</ToString></Obj></Objs>'
        self.assertEqual(clean_output('Result\n#< CLIXML\n'+progress+'\nDone'),'Result\n\nDone')
        self.assertEqual(clean_output('error <script>test</script>\n'), 'error <script>test</script>\n')
        self.assertEqual(clean_output(self.prefix+'<Obj S="progress" RefId="0"><TN RefId="0">'),'')
    def test_errors_and_warnings_are_preserved(self):
        text=self.prefix+'<Obj S="progress"><ToString>Loading</ToString></Obj><S S="Error">Access denied_x000D__x000A_</S><S S="warning">Warning &amp; details</S></Objs>'
        self.assertEqual(clean_output(text),'Access denied\r\n\nWarning & details')
        incomplete=self.prefix+'<S S="Error">Partial'
        self.assertEqual(clean_output(incomplete),incomplete)
