param(
    [Parameter(Mandatory=$true)][string]$JavaHome,
    [Parameter(Mandatory=$true)][string]$PostgresBin,
    [Parameter(Mandatory=$true)][string]$Python,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$run = Join-Path $repo ('ai-worker/data/spring-integration/run-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
$JavaHome = (Resolve-Path $JavaHome).Path
$PostgresBin = (Resolve-Path $PostgresBin).Path
$Python = (Resolve-Path $Python).Path
$java = Join-Path $JavaHome 'bin/java.exe'
$pgdata = Join-Path $run 'pgdata'
$clock = Join-Path $run 'clock.txt'
[IO.File]::WriteAllText($clock, '2026-10-16T18:00:00+09:00')
function Free-Port {
    $socket = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $socket.Start()
    try { return $socket.LocalEndpoint.Port } finally { $socket.Stop() }
}
function Wait-Url([string]$url, [Diagnostics.Process]$process) {
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($process.HasExited) { throw "Process exited while waiting for $url; see $run" }
        try {
            $response = Invoke-WebRequest $url -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { Start-Sleep -Milliseconds 200 }
    }
    throw "Readiness timeout for $url; see $run"
}
$pgport, $workerport, $apiport = (Free-Port), (Free-Port), (Free-Port)
while ($workerport -eq $pgport) { $workerport = Free-Port }
while ($apiport -in @($pgport, $workerport)) { $apiport = Free-Port }
$processes = @{}
$oldEnv = @{}
foreach ($name in @('JAVA_HOME','PYTHONPATH','BULLBEAR_TEST_API_URL','BULLBEAR_TEST_CLOCK_FILE','BULLBEAR_TEST_RECOVERY_CONFIG','BULLBEAR_TEST_JDBC_URL','BULLBEAR_TEST_DB_USER')) {
    $oldEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$result = @{run_directory=$run; postgres_port=$pgport; worker_port=$workerport; api_port=$apiport;
            market_and_model='synthetic_fixture'; scoring_clock='simulated'; status='running'}
try {
    $env:JAVA_HOME = $JavaHome
    if (-not $SkipBuild) {
        Push-Location (Join-Path $repo 'api')
        try {
            & .\gradlew.bat test --tests '*HttpWorkerClientTest' --tests '*ScoreRuleTest' --tests '*StartDebateRequestTest' bootJar --no-daemon
            if ($LASTEXITCODE -ne 0) { throw 'Gradle build/test failed' }
        } finally { Pop-Location }
    }
    & (Join-Path $PostgresBin 'initdb.exe') -D $pgdata -U bullbear --auth=trust --locale=C --encoding=UTF8 *> (Join-Path $run 'initdb.log')
    if ($LASTEXITCODE -ne 0) { throw 'Postgres initialization failed' }
    $processes.postgres = Start-Process (Join-Path $PostgresBin 'postgres.exe') -ArgumentList @('-D', ('"'+$pgdata+'"'), '-h', '127.0.0.1', '-p', $pgport) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $run 'postgres.out.log') -RedirectStandardError (Join-Path $run 'postgres.err.log')
    $env:PYTHONPATH = Join-Path $repo 'ai-worker/src'
    $processes.worker = Start-Process $Python -WorkingDirectory (Join-Path $repo 'ai-worker') -ArgumentList @('-m','tests.http_fixture','--uncertain-usage','--port',$workerport,'--data',('"'+(Join-Path $run 'worker')+'"'),'--clock-file',('"'+$clock+'"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $run 'worker.out.log') -RedirectStandardError (Join-Path $run 'worker.err.log')
    Wait-Url "http://127.0.0.1:$workerport/health" $processes.worker
    $jar = Get-ChildItem (Join-Path $repo 'api/build/libs/*.jar') | Where-Object Name -NotLike '*-plain.jar' | Select-Object -First 1
    if (-not $jar) { throw 'Spring bootJar is missing' }
    $arguments = @('-jar', ('"'+$jar.FullName+'"'), '--server.address=127.0.0.1', "--server.port=$apiport",
        "--spring.datasource.url=jdbc:postgresql://127.0.0.1:$pgport/postgres", '--spring.datasource.username=bullbear',
        '--bullbear.worker.mode=http', "--bullbear.worker.base-url=http://127.0.0.1:$workerport", '--bullbear.worker.token=integration-test-token',
        '--bullbear.forward-run.enabled=false', '"--bullbear.scoring.cron=*/1 * * * * *"',
        '--bullbear.experiment.start=2026-10-01', '--bullbear.experiment.single-enabled=true',
        '--bullbear.experiment.poll-interval=1s')
    $processes.spring = Start-Process $java -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $run 'spring.out.log') -RedirectStandardError (Join-Path $run 'spring.err.log')
    Wait-Url "http://127.0.0.1:$apiport/actuator/health" $processes.spring
    $env:BULLBEAR_TEST_JDBC_URL = "jdbc:postgresql://127.0.0.1:$pgport/postgres"
    $env:BULLBEAR_TEST_DB_USER = 'bullbear'
    Push-Location (Join-Path $repo 'api')
    try {
        & .\gradlew.bat test --tests '*SingleVerdictRecoveryTest' --no-daemon
        if ($LASTEXITCODE -ne 0) { throw 'Single execution recovery database tests failed' }
    } finally { Pop-Location }
    $result.process_ids = @{}
    foreach ($key in $processes.Keys) { $result.process_ids[$key] = $processes[$key].Id }
    $env:BULLBEAR_TEST_API_URL = "http://127.0.0.1:$apiport"
    $env:BULLBEAR_TEST_CLOCK_FILE = $clock
    $env:BULLBEAR_TEST_RECOVERY_CONFIG = Join-Path $run 'recovery-config.json'
    $jdbcDriver = Get-ChildItem (Join-Path $env:USERPROFILE '.gradle/caches/modules-2/files-2.1/org.postgresql/postgresql') -Recurse -Filter '*.jar' | Select-Object -First 1
    if (-not $jdbcDriver) { throw 'PostgreSQL JDBC driver missing from Gradle cache' }
    @{worker_data=(Join-Path $run 'worker'); worker_url="http://127.0.0.1:$workerport";
      restart_command=@($Python,'-m','tests.http_fixture','--port',"$workerport",'--data',(Join-Path $run 'worker'),'--clock-file',$clock);
      sql_command=@($java,'--class-path',$jdbcDriver.FullName,(Join-Path $PSScriptRoot 'FixtureSql.java'),"jdbc:postgresql://127.0.0.1:$pgport/postgres")
    } | ConvertTo-Json -Depth 4 | Set-Content $env:BULLBEAR_TEST_RECOVERY_CONFIG -Encoding utf8
    Push-Location (Join-Path $repo 'ai-worker')
    try {
        & $Python -m pytest tests/test_spring_integration.py tests/test_spring_single.py tests/test_spring_usage_recovery.py -q --junitxml (Join-Path $run 'integration.xml') 2>&1 | Tee-Object (Join-Path $run 'pytest.log')
        $result.test_exit_code = $LASTEXITCODE
        if ($LASTEXITCODE -ne 0) { throw 'Spring integration tests failed' }
    } finally { Pop-Location }
    $result.status = 'passed'
} catch {
    $result.status = 'failed'
    $result.error = $_.Exception.Message
    throw
} finally {
    foreach ($key in @('spring','worker')) {
        if ($processes.ContainsKey($key) -and -not $processes[$key].HasExited) {
            Stop-Process -Id $processes[$key].Id
            $processes[$key].WaitForExit(10000) | Out-Null
        }
    }
    if ($processes.ContainsKey('postgres') -and -not $processes.postgres.HasExited) {
        & (Join-Path $PostgresBin 'pg_ctl.exe') -D $pgdata -m fast -w stop *> (Join-Path $run 'postgres-stop.log')
    }
    foreach ($name in $oldEnv.Keys) { [Environment]::SetEnvironmentVariable($name, $oldEnv[$name], 'Process') }
    $result.processes_alive_after_cleanup = @($processes.Values | Where-Object { -not $_.HasExited } | ForEach-Object Id)
    $result.finished_at = [DateTime]::UtcNow.ToString('o')
    $result | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $run 'result.json') -Encoding utf8
    Write-Host "Integration artifacts: $run"
}
