# Database Search System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/dbsearcher.cpp](src/dbsearcher.cpp)
- [src/dbsearcher.h](src/dbsearcher.h)
- [src/mufilter.cpp](src/mufilter.cpp)
- [src/postmufilter.cpp](src/postmufilter.cpp)
- [src/profileloader.cpp](src/profileloader.cpp)
- [src/profileloader.h](src/profileloader.h)
- [src/runquery.cpp](src/runquery.cpp)
- [src/search.cpp](src/search.cpp)

</details>



## Purpose and Scope

The Database Search System is the core component responsible for performing protein structure searches against databases of protein chains. It orchestrates multi-threaded database loading, query processing, and filtering operations to efficiently find structurally similar proteins. This system handles both query-versus-database searches and self-searches (all-versus-all comparisons within a single database).

For information about the underlying alignment algorithms, see [Core Alignment Engine](#3). For details about data format handling, see [Data Processing and Formats](#5).

## Architecture Overview

The Database Search System employs a multi-stage architecture designed for scalability and performance:

```mermaid
graph TB
    subgraph "Command Interface"
        CMD["cmd_search()"]
        SELF["SelfSearch()"]
        NOFILTER["Search_NoMuFilter()"]
    end
    
    subgraph "Database Search Orchestrator"
        DBS["DBSearcher"]
        SETUP["Setup()"]
        LOADDB["LoadDB()"]
        RUNQUERY["RunQuery()"]
        RUNSELF["RunSelf()"]
    end
    
    subgraph "Profile Loading System"
        PL["ProfileLoader"]
        PLTHREAD["ThreadBody()"]
        PLLOAD["Load()"]
    end
    
    subgraph "Filtering Pipeline"
        MUFILTER["MuPreFilter()"]
        POSTMU["PostMuFilter()"]
        REJECT["Reject()"]
    end
    
    subgraph "Multi-Threading"
        QTHREAD["ThreadBodyQuery()"]
        STHREAD["ThreadBodySelf()"]
        STATIC["StaticThreadBody()"]
    end
    
    subgraph "Core Processing"
        DA["DSSAligner"]
        DSS["DSS"]
        CHAIN["PDBChain"]
        PROFILE["Profile Data"]
    end
    
    CMD --> DBS
    SELF --> DBS
    NOFILTER --> DBS
    
    DBS --> SETUP
    DBS --> LOADDB
    DBS --> RUNQUERY
    DBS --> RUNSELF
    
    LOADDB --> PL
    PL --> PLTHREAD
    PL --> PLLOAD
    
    RUNQUERY --> MUFILTER
    MUFILTER --> POSTMU
    DBS --> REJECT
    
    RUNQUERY --> QTHREAD
    RUNSELF --> STHREAD
    PL --> STATIC
    
    QTHREAD --> DA
    STHREAD --> DA
    PLTHREAD --> DSS
    DA --> CHAIN
    DSS --> PROFILE
```

**Database Search System Architecture**

Sources: [src/search.cpp:1-116](), [src/dbsearcher.h:14-109](), [src/dbsearcher.cpp:1-283](), [src/profileloader.h:8-37]()

## Core Components

### DBSearcher Class

The `DBSearcher` class serves as the primary orchestrator for database search operations:

| Component | Purpose | Key Methods |
|-----------|---------|-------------|
| Database Management | Loads and manages database chains | `LoadDB()`, `GetDBChainCount()` |
| Threading Control | Manages multi-threaded execution | `ThreadBodyQuery()`, `ThreadBodySelf()` |
| Search Orchestration | Coordinates query and self-search modes | `RunQuery()`, `RunSelf()` |
| Result Filtering | Applies E-value and statistical filters | `Reject()`, `BaseOnAln()` |

```mermaid
graph LR
    subgraph "DBSearcher State"
        PARAMS["m_Params"]
        THREADS["m_ThreadCount"]
        DAS["m_DAs[]"]
        MEMS["m_Mems[]"]
    end
    
    subgraph "Database Storage"
        CHAINS["m_DBChains[]"]
        PROFILES["m_DBProfiles[]"]
        MULETTERS["m_DBMuLettersVec[]"]
        MUKMERS["m_DBMuKmersVec[]"]
        SELFREV["m_DBSelfRevScores[]"]
    end
    
    subgraph "Search Progress"
        PROCQUERY["m_ProcessedQueryCount"]
        PROCPAIR["m_ProcessedPairCount"]
        HITCOUNT["m_HitCount"]
        MAXEVAL["m_MaxEvalue"]
    end
    
    subgraph "Threading Synchronization"
        LOCK["m_Lock"]
        NEXTCHAIN["m_NextChainIndex1/2"]
        NEXTQUERY["m_NextQueryIdx"]
        NEXTDB["m_NextDBIdx"]
    end
    
    PARAMS --> CHAINS
    THREADS --> DAS
    DAS --> PROFILES
    PROFILES --> MULETTERS
    MULETTERS --> MUKMERS
    MUKMERS --> SELFREV
    
    PROCQUERY --> LOCK
    PROCPAIR --> LOCK
    HITCOUNT --> LOCK
    MAXEVAL --> LOCK
    
    LOCK --> NEXTCHAIN
    LOCK --> NEXTQUERY
    LOCK --> NEXTDB
```

**DBSearcher Class Structure**

Sources: [src/dbsearcher.h:14-109](), [src/dbsearcher.cpp:12-283]()

### ProfileLoader Class

The `ProfileLoader` handles multi-threaded loading of protein chain profiles:

```mermaid
graph TB
    subgraph "ProfileLoader Interface"
        LOAD["Load()"]
        THREADBODY["ThreadBody()"]
        STATIC["StaticThreadBody()"]
    end
    
    subgraph "Input Sources"
        CR["ChainReader2"]
        PARAMS["DSSParams"]
        THREADCOUNT["ThreadCount"]
    end
    
    subgraph "Output Containers"
        CHAINS["Chains[]"]
        PROFILES["Profiles[]"]
        MULETTERS["MuLetters[]"]
        KMERS["KmersVec[]"]
        SELFREV["SelfRevScores[]"]
    end
    
    subgraph "Processing Objects"
        DSS["DSS"]
        DA["DSSAligner"]
        CHAIN["PDBChain"]
    end
    
    subgraph "Thread Management"
        LOCK["m_Lock"]
        COUNT["m_Count"]
        PROGRESS["m_LastProgress"]
    end
    
    LOAD --> CR
    LOAD --> PARAMS
    LOAD --> THREADCOUNT
    LOAD --> STATIC
    
    STATIC --> THREADBODY
    THREADBODY --> DSS
    THREADBODY --> DA
    THREADBODY --> CHAIN
    
    DSS --> PROFILES
    DSS --> MULETTERS
    DSS --> KMERS
    DA --> SELFREV
    
    THREADBODY --> LOCK
    LOCK --> COUNT
    LOCK --> PROGRESS
    
    CHAINS --> PROFILES
    PROFILES --> MULETTERS
    MULETTERS --> KMERS
    KMERS --> SELFREV
```

**ProfileLoader Multi-threading Architecture**

Sources: [src/profileloader.cpp:1-112](), [src/profileloader.h:8-37]()

## Search Workflow

The database search follows a structured workflow depending on the search mode:

### Query vs Database Search

```mermaid
graph TD
    subgraph "Initialization"
        LOADDB["LoadDB(DBFN)"]
        SETUP["Setup()"]
        STATSIG["StatSig::Init()"]
    end
    
    subgraph "Query Processing"
        OPENQUERY["Open Query CR"]
        RUNQUERY["RunQuery(CR)"]
        THREADBODY["ThreadBodyQuery()"]
    end
    
    subgraph "Per-Query Processing"
        GETCHAIN["GetNext() Chain"]
        INITDSS["D.Init(*Chain)"]
        GETPROFILE["D.GetProfile()"]
        GETMULETTERS["D.GetMuLetters()"]
        GETMUKMERS["D.GetMuKmers()"]
        SETQUERY["DA.SetQuery()"]
    end
    
    subgraph "Database Scanning"
        DBLOOP["for DBChainIdx in DB"]
        SETTARGET["DA.SetTarget()"]
        ALIGN["DA.AlignQueryTarget()"]
        BASEONALN["BaseOnAln()"]
        REJECT["Reject()"]
    end
    
    subgraph "Output"
        TOTSV["DA.ToTsv()"]
        TOALN["DA.ToAln()"]
        TOFASTA["DA.ToFasta2()"]
    end
    
    LOADDB --> SETUP
    SETUP --> STATSIG
    STATSIG --> OPENQUERY
    OPENQUERY --> RUNQUERY
    RUNQUERY --> THREADBODY
    
    THREADBODY --> GETCHAIN
    GETCHAIN --> INITDSS
    INITDSS --> GETPROFILE
    GETPROFILE --> GETMULETTERS
    GETMULETTERS --> GETMUKMERS
    GETMUKMERS --> SETQUERY
    
    SETQUERY --> DBLOOP
    DBLOOP --> SETTARGET
    SETTARGET --> ALIGN
    ALIGN --> BASEONALN
    BASEONALN --> REJECT
    
    REJECT --> TOTSV
    TOTSV --> TOALN
    TOALN --> TOFASTA
```

**Query vs Database Search Workflow**

Sources: [src/search.cpp:40-62](), [src/runquery.cpp:18-125]()

### Self-Search Mode

```mermaid
graph TD
    subgraph "Self-Search Setup"
        SELFCMD["SelfSearch()"]
        LOADSELF["LoadDB(QFN)"]
        SETUPSELF["Setup()"]
        RUNSELF["RunSelf()"]
    end
    
    subgraph "Pair Generation"
        GETNEXTPAIR["GetNextPairSelf()"]
        CHAINIDX1["ChainIndex1"]
        CHAINIDX2["ChainIndex2"]
        PAIRINDEX["m_PairIndex"]
    end
    
    subgraph "Pair Processing"
        THREADSELF["ThreadBodySelf()"]
        SETQUERY2["SetQuery(Chain1)"]
        SETTARGET2["SetTarget(Chain2)"]
        ALIGN2["AlignQueryTarget()"]
        BASEONALN2["BaseOnAln()"]
    end
    
    subgraph "Synchronization"
        LOCK["m_Lock"]
        NEXTCHAIN1["m_NextChainIndex1"]
        NEXTCHAIN2["m_NextChainIndex2"]
        PAIRCOUNT["m_PairCount"]
    end
    
    SELFCMD --> LOADSELF
    LOADSELF --> SETUPSELF
    SETUPSELF --> RUNSELF
    RUNSELF --> THREADSELF
    
    THREADSELF --> GETNEXTPAIR
    GETNEXTPAIR --> LOCK
    LOCK --> NEXTCHAIN1
    LOCK --> NEXTCHAIN2
    LOCK --> PAIRCOUNT
    
    NEXTCHAIN1 --> CHAINIDX1
    NEXTCHAIN2 --> CHAINIDX2
    CHAINIDX1 --> SETQUERY2
    CHAINIDX2 --> SETTARGET2
    
    SETQUERY2 --> ALIGN2
    SETTARGET2 --> ALIGN2
    ALIGN2 --> BASEONALN2
    
    PAIRINDEX --> PAIRCOUNT
```

**Self-Search Workflow**

Sources: [src/search.cpp:20-38](), [src/runself.cpp:1-100]()

## Multi-Threading Model

The system employs a sophisticated multi-threading approach across multiple components:

### Thread Distribution

| Component | Thread Function | Purpose |
|-----------|----------------|---------|
| ProfileLoader | `StaticThreadBody()` | Load chain profiles in parallel |
| DBSearcher Query | `ThreadBodyQuery()` | Process query chains against DB |
| DBSearcher Self | `ThreadBodySelf()` | Process chain pairs in self-search |
| PostMuFilter | `ThreadBody_IndexQuery()` | Index queries for post-filtering |
| PostMuFilter | `ThreadBody_Scan()` | Scan filtered pairs |

### Thread Synchronization

```mermaid
graph TB
    subgraph "DBSearcher Threading"
        LOCK1["m_Lock"]
        PROCQUERY["m_ProcessedQueryCount"]
        PROCPAIR["m_ProcessedPairCount"]
        HITCOUNT["m_HitCount"]
        LASTPROG["m_LastProgress"]
    end
    
    subgraph "ProfileLoader Threading"
        LOCK2["m_Lock"]
        COUNT["m_Count"]
        CHAINS["m_Chains->push_back()"]
        PROFILES["m_Profiles->push_back()"]
    end
    
    subgraph "PostMuFilter Threading"
        INDEXLOCK["s_IndexQueryLock"]
        SCANLOCK["s_ScanLock"]
        QUERYIDX["s_QueryIdx"]
        LINEIDX["s_LineIdx"]
    end
    
    subgraph "Per-Thread Resources"
        DAS["m_DAs[]"]
        MEMS["m_Mems[]"]
        XDPMEM["XDPMem"]
        DSSALIGNER["DSSAligner"]
    end
    
    LOCK1 --> PROCQUERY
    LOCK1 --> PROCPAIR
    LOCK1 --> HITCOUNT
    LOCK1 --> LASTPROG
    
    LOCK2 --> COUNT
    LOCK2 --> CHAINS
    LOCK2 --> PROFILES
    
    INDEXLOCK --> QUERYIDX
    SCANLOCK --> LINEIDX
    
    DAS --> DSSALIGNER
    MEMS --> XDPMEM
```

**Multi-Threading Synchronization Model**

Sources: [src/dbsearcher.cpp:73-115](), [src/profileloader.cpp:41-70](), [src/postmufilter.cpp:36-101]()

## Filtering Pipeline

The system implements a two-stage filtering approach for efficient search:

### Pre-filtering (MuFilter)

```mermaid
graph LR
    subgraph "Query Preparation"
        QUERYDB["SeqDB QueryDB"]
        MUDEX["MuDex Index"]
        MULETTERS["MuLetters[]"]
        MUKMERS["MuKmers[]"]
    end
    
    subgraph "Target Processing"
        FSS["SeqSource FSS"]
        THREADBODY["ThreadBody()"]
        TARGETMU["Target MuLetters"]
        TARGETKMERS["Target MuKmers"]
    end
    
    subgraph "Filtering Logic"
        KMERMATCH["K-mer Matching"]
        XDROP["MuXDrop()"]
        HSPSCORE["HSP Score"]
        OMEGA["GetOmega()"]
        ADDSCORE["AddScore()"]
    end
    
    subgraph "Output"
        SCOREVEC["s_QueryIdxToScoreVec"]
        TARGETVEC["s_QueryIdxToTargetIdxVec"]
        TRUNCATE["TruncateVecs()"]
        FILTERTSV["Filter TSV Output"]
    end
    
    QUERYDB --> MUDEX
    MUDEX --> MULETTERS
    MULETTERS --> MUKMERS
    
    FSS --> THREADBODY
    THREADBODY --> TARGETMU
    TARGETMU --> TARGETKMERS
    
    MUKMERS --> KMERMATCH
    TARGETKMERS --> KMERMATCH
    KMERMATCH --> XDROP
    XDROP --> HSPSC
    HSPSCORE --> OMEGA
    OMEGA --> ADDSCORE
    
    ADDSCORE --> SCOREVEC
    ADDSCORE --> TARGETVEC
    SCOREVEC --> TRUNCATE
    TARGETVEC --> TRUNCATE
    TRUNCATE --> FILTERTSV
```

**Pre-filtering Pipeline (MuFilter)**

Sources: [src/mufilter.cpp:313-569]()

### Post-filtering (PostMuFilter)

```mermaid
graph TB
    subgraph "Input Processing"
        FILTERTSV["MuFilter TSV"]
        QUERYCA["Query CA File"]
        DBBCA["DB BCA File"]
        LINEREADER["LineReader2"]
    end
    
    subgraph "Query Indexing Phase"
        INDEXTHREAD["ThreadBody_IndexQuery()"]
        QCHAIN["Query Chain"]
        QPROFILE["Query Profile"]
        QMULETTERS["Query MuLetters"]
        QSELFREV["Query SelfRevScore"]
        CHAINBAG["ChainBag"]
    end
    
    subgraph "Scanning Phase"
        SCANTHREAD["ThreadBody_Scan()"]
        DBCHAIN["DB Chain"]
        DBPROFILE["DB Profile"]
        DBMULETTERS["DB MuLetters"]
        DBSELFREV["DB SelfRevScore"]
    end
    
    subgraph "Alignment & Output"
        ALIGNBAGS["AlignBags()"]
        EVALCHECK["E-value Check"]
        TOTSV2["ToTsv()"]
        HITSFILE["Hits File"]
    end
    
    FILTERTSV --> LINEREADER
    QUERYCA --> INDEXTHREAD
    DBBCA --> SCANTHREAD
    
    INDEXTHREAD --> QCHAIN
    QCHAIN --> QPROFILE
    QPROFILE --> QMULETTERS
    QMULETTERS --> QSELFREV
    QSELFREV --> CHAINBAG
    
    SCANTHREAD --> DBCHAIN
    DBCHAIN --> DBPROFILE
    DBPROFILE --> DBMULETTERS
    DBMULETTERS --> DBSELFREV
    
    CHAINBAG --> ALIGNBAGS
    DBSELFREV --> ALIGNBAGS
    ALIGNBAGS --> EVALCHECK
    EVALCHECK --> TOTSV2
    TOTSV2 --> HITSFILE
```

**Post-filtering Pipeline (PostMuFilter)**

Sources: [src/postmufilter.cpp:194-308]()

## Performance Monitoring

The system provides comprehensive performance tracking:

### Statistics Collection

```mermaid
graph LR
    subgraph "Search Statistics"
        SECS["m_Secs"]
        PROCQUERY["m_ProcessedQueryCount"]
        PROCPAIR["m_ProcessedPairCount"]
        HITCOUNT["m_HitCount"]
        MAXEVAL["m_MaxEvalue"]
    end
    
    subgraph "Threading Metrics"
        THREADCOUNT["ThreadCount"]
        PERSEC["QueriesPerSec"]
        PAIRSPERSEC["PairsPerSec"]
        PERSECTHREAD["PairsPerSecPerThread"]
    end
    
    subgraph "Cache Statistics"
        CACHEHITS["m_QPCacheHits"]
        CACHEMISS["m_QPCacheMisses"]
        DALIGNCOUNT["DSSAligner::m_AlnCount"]
        ALNSPERSEC["m_AlnsPerThreadPerSec"]
    end
    
    subgraph "Output Reporting"
        RUNSTATS["RunStats()"]
        PROGRESSLOG["ProgressLog()"]
        SECSTOHHMMSS["SecsToHHMMSS()"]
        INTTOSTR["IntToStr()"]
    end
    
    SECS --> PERSEC
    PROCQUERY --> PERSEC
    PROCPAIR --> PAIRSPERSEC
    THREADCOUNT --> PERSECTHREAD
    PAIRSPERSEC --> PERSECTHREAD
    
    CACHEHITS --> RUNSTATS
    CACHEMISS --> RUNSTATS
    DALIGNCOUNT --> ALNSPERSEC
    
    RUNSTATS --> PROGRESSLOG
    PROGRESSLOG --> SECSTOHHMMSS
    PROGRESSLOG --> INTTOSTR
    
    HITCOUNT --> RUNSTATS
    MAXEVAL --> RUNSTATS
```

**Performance Monitoring System**

Sources: [src/dbsearcher.cpp:29-56](), [src/runquery.cpp:118-125]()

---