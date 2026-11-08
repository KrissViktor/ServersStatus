using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.ServiceProcess;
using System.Threading;
using System.Xml.Serialization;

public class Settings {
    public string Executable, Arguments, WorkingDirectory;
    public int CpuPercent=80, MemoryMB=22528, ReserveMB=4096;
}
public sealed class AIService : ServiceBase {
    readonly string root=AppDomain.CurrentDomain.BaseDirectory;
    readonly object logLock=new object();
    volatile bool stopping; Thread worker; Process child; IntPtr job=IntPtr.Zero;
    [StructLayout(LayoutKind.Sequential)] struct IO { public ulong a,b,c,d,e,f; }
    [StructLayout(LayoutKind.Sequential)] struct Basic {public long a,b;public uint flags;public UIntPtr min,max;public uint active;public UIntPtr affinity;public uint priority,scheduling;}
    [StructLayout(LayoutKind.Sequential)] struct Limits {public Basic basic;public IO io;public UIntPtr processMemory,jobMemory,peakProcess,peakJob;}
    [StructLayout(LayoutKind.Sequential)] struct CPU {public uint flags,rate;}
    [StructLayout(LayoutKind.Sequential)] struct Memory {public uint length,load;public ulong total,available,pageTotal,pageAvailable,virtualTotal,virtualAvailable,extended;}
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr a,string name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(IntPtr j,int type,IntPtr data,uint size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr j,IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GlobalMemoryStatusEx(ref Memory m);
    public AIService(){ServiceName="ServersStatusAI";CanStop=true;AutoLog=false;}
    public static void Main(){ServiceBase.Run(new AIService());}
    protected override void OnStart(string[] args){stopping=false;worker=new Thread(Run);worker.IsBackground=true;worker.Start();}
    protected override void OnStop(){stopping=true;if(worker!=null&&!worker.Join(15000))Log("Supervisor is still stopping");}
    void Log(string message){lock(logLock){try{string p=Path.Combine(root,"logs","service.log");if(File.Exists(p)&&new FileInfo(p).Length>20*1024*1024){File.Delete(p+".1");File.Move(p,p+".1");}File.AppendAllText(p,DateTime.UtcNow.ToString("o")+" "+message+Environment.NewLine);}catch{}}}
    static void Set<T>(IntPtr j,int type,T value) where T:struct {int n=Marshal.SizeOf(typeof(T));IntPtr p=Marshal.AllocHGlobal(n);try{Marshal.StructureToPtr(value,p,false);if(!SetInformationJobObject(j,type,p,(uint)n))throw new System.ComponentModel.Win32Exception();}finally{Marshal.FreeHGlobal(p);}}
    void StartModel(Settings s){
        job=CreateJobObject(IntPtr.Zero,null);if(job==IntPtr.Zero)throw new System.ComponentModel.Win32Exception();
        Limits limit=new Limits();limit.basic.flags=0x2000|0x200|0x20;limit.basic.priority=0x4000;limit.jobMemory=new UIntPtr((ulong)s.MemoryMB*1024*1024);Set(job,9,limit);
        CPU cpu=new CPU();cpu.flags=5;cpu.rate=(uint)s.CpuPercent*100;Set(job,15,cpu);
        ProcessStartInfo start=new ProcessStartInfo(s.Executable,s.Arguments);start.WorkingDirectory=s.WorkingDirectory;start.UseShellExecute=false;start.CreateNoWindow=true;start.RedirectStandardOutput=true;start.RedirectStandardError=true;
        child=new Process();child.StartInfo=start;child.OutputDataReceived+=(a,e)=>{if(e.Data!=null)Log(e.Data);};child.ErrorDataReceived+=(a,e)=>{if(e.Data!=null)Log(e.Data);};
        child.Start();
        if(!AssignProcessToJobObject(job,child.Handle)){child.Kill();throw new System.ComponentModel.Win32Exception();}
        child.BeginOutputReadLine();child.BeginErrorReadLine();Log("Model started; CPU cap "+s.CpuPercent+"%; committed-memory cap "+s.MemoryMB+" MB; below-normal priority");
    }
    void StopModel(){if(job!=IntPtr.Zero){CloseHandle(job);job=IntPtr.Zero;}if(child!=null){try{if(!child.WaitForExit(10000))child.Kill();}catch{}child.Dispose();child=null;}}
    string ReadPause(string p){try{return File.ReadAllText(p);}catch(FileNotFoundException){return "0";}}
    bool Paused(){string p=Path.Combine(root,"pause-until.txt");if(!File.Exists(p))return false;long until;return !long.TryParse(ReadPause(p).Trim(),out until)||DateTimeOffset.UtcNow.ToUnixTimeSeconds()<until;}
    void Run(){
        try{
            Settings s;using(var f=File.OpenRead(Path.Combine(root,"settings.xml")))s=(Settings)new XmlSerializer(typeof(Settings)).Deserialize(f);
            if(s.CpuPercent<1||s.CpuPercent>80||s.MemoryMB<32||s.MemoryMB>25600||s.ReserveMB<0||s.ReserveMB>32768)throw new InvalidOperationException("Invalid resource settings");
            string last="";
            while(!stopping){
                Memory m=new Memory();m.length=(uint)Marshal.SizeOf(typeof(Memory));if(!GlobalMemoryStatusEx(ref m))throw new System.ComponentModel.Win32Exception();
                bool pause=Paused();ulong need=(ulong)(child==null?s.MemoryMB+s.ReserveMB:s.ReserveMB)*1024*1024;
                if(pause||m.available<need){if(child!=null)StopModel();string reason=pause?"Paused for backup/maintenance":"Waiting for free RAM";if(last!=reason){Log(reason);last=reason;}}
                else if(child==null){StartModel(s);last="Running";}
                else if(child.HasExited)throw new InvalidOperationException("Model process exited; SCM recovery will restart service");
                for(int i=0;i<20&&!stopping;i++)Thread.Sleep(100);
            }
        }catch(Exception e){Log("Supervisor failed: "+e.GetType().Name+": "+e.Message);StopModel();if(!stopping)Environment.Exit(1);}
        finally{StopModel();}
    }
}
