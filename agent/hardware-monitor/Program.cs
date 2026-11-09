using System.Text;
using System.Text.Json;
using LibreHardwareMonitor.Hardware;

// One bounded local probe; the Python agent owns scheduling and the hard timeout.
// No listener, sensor controls, firmware writes or security-policy changes.
Console.OutputEncoding = new UTF8Encoding(false);
var rows = new List<object>();
if (args.Contains("--self-test"))
{
    Console.WriteLine("[]"); // Exercise the bundled runtime without loading hardware drivers.
    return;
}
if (!OperatingSystem.IsWindows())
{
    Console.WriteLine("[]");
    return;
}
var computer = new Computer
{
    IsCpuEnabled = true,
    IsGpuEnabled = true,
    IsMemoryEnabled = true,
    IsMotherboardEnabled = true,
    IsStorageEnabled = true,
    IsControllerEnabled = true,
    IsPsuEnabled = true,
    IsBatteryEnabled = true
};
try
{
    computer.Open();
    foreach (var hardware in computer.Hardware)
    {
        try { Read(hardware, 0); } catch (Exception) { }
    }
}
catch (Exception)
{
    Console.Error.WriteLine("Hardware probe incomplete; some devices or drivers are unavailable.");
}
finally
{
    try { computer.Close(); } catch (Exception) { }
}
Console.WriteLine(JsonSerializer.Serialize(rows));

void Read(IHardware hardware, int depth)
{
    if (depth > 8 || rows.Count >= 512) return;
    try { hardware.Update(); } catch (Exception) { }
    foreach (var sensor in hardware.Sensors)
    {
        if (sensor.SensorType != SensorType.Temperature) continue;
        rows.Add(new
        {
            id = "lhm:" + sensor.Identifier,
            label = sensor.Name,
            device = hardware.Name,
            component = hardware.HardwareType.ToString(),
            source = "LibreHardwareMonitor (built-in)",
            current = sensor.Value is float number && float.IsFinite(number) ? (float?)number : null
        });
        if (rows.Count >= 512) return;
    }
    foreach (var child in hardware.SubHardware)
    {
        try { Read(child, depth + 1); } catch (Exception) { }
    }
}
