#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/mobility-module.h"
#include "ns3/propagation-module.h"
#include "ns3/spectrum-module.h"
#include "ns3/lr-wpan-module.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>
using namespace ns3;

struct Event { double t; int state; };
struct Counters {
    std::array<unsigned,3> phyTx{},phyTxBytes{};
    std::array<unsigned,3> confirms{},success{},noAck{},accessFail{},other{};
    std::array<unsigned,3> mask{},uniqueRx{};
    std::array<double,3> lastConfirm{},lastRx{},start{};
    std::array<std::vector<Event>,3> states;
    unsigned rxDrop=0,badPayload=0;
};
static Counters z;

static void OnRx(McpsDataIndicationParams, Ptr<Packet> p) {
    uint8_t bytes[104]={};
    if (p->GetSize()!=104 || p->CopyData(bytes,sizeof(bytes))!=104 ||
        bytes[0]<1 || bytes[0]>2 || bytes[1]>=5 || bytes[2]!=5 ||
        bytes[3]!=(uint8_t)(bytes[0]^bytes[1]^5)) { ++z.badPayload;return; }
    unsigned id=bytes[0],bit=1u<<bytes[1];
    if (!(z.mask[id]&bit)) { z.mask[id]|=bit;++z.uniqueRx[id];z.lastRx[id]=Simulator::Now().GetSeconds(); }
}
static void OnDrop(Ptr<const Packet>) {++z.rxDrop;}
static void OnTx(unsigned id,Ptr<const Packet> p) {++z.phyTx[id];z.phyTxBytes[id]+=p->GetSize();}
static void OnState(unsigned id,Time, LrWpanPhyEnumeration, LrWpanPhyEnumeration after) {
    z.states[id].push_back({Simulator::Now().GetSeconds(),(int)after});
}
static void OnConfirm(unsigned id, McpsDataConfirmParams p) {
    ++z.confirms[id];z.lastConfirm[id]=Simulator::Now().GetSeconds();
    if(p.m_status==LrWpanMacStatus::SUCCESS)++z.success[id];
    else if(p.m_status==LrWpanMacStatus::NO_ACK)++z.noAck[id];
    else if(p.m_status==LrWpanMacStatus::CHANNEL_ACCESS_FAILURE)++z.accessFail[id];
    else ++z.other[id];
}
static void Send(Ptr<LrWpanMac> mac, McpsDataRequestParams req, unsigned id) {
    for(unsigned seq=0;seq<5;++seq) {
        std::array<uint8_t,104> data{};
        data[0]=id;data[1]=seq;data[2]=5;data[3]=id^seq^5;
        req.m_msduHandle=(uint8_t)(id*16+seq);
        mac->McpsDataRequest(req,Create<Packet>(data.data(),data.size()));
    }
}
static double Energy(unsigned id,double begin,double end) {
    // Approximate CC2420 RF-state energy, excluding unmodelled states and CPU.
    int state=(int)IEEE_802_15_4_PHY_TRX_OFF;
    double last=0,tx=0,rx=0;
    auto accrue=[&](double a,double b,int s) {
        double dt=std::max(0.,std::min(end,b)-std::max(begin,a));
        if(s==(int)IEEE_802_15_4_PHY_TX_ON || s==(int)IEEE_802_15_4_PHY_BUSY_TX)tx+=dt;
        if(s==(int)IEEE_802_15_4_PHY_RX_ON || s==(int)IEEE_802_15_4_PHY_BUSY_RX)rx+=dt;
    };
    for(const auto& e:z.states[id]) {accrue(last,e.t,state);last=e.t;state=e.state;}
    accrue(last,end,state);
    return 3.3*(.0174*tx+.0188*rx);
}
static void Run(const std::string& mode, unsigned run) {
    z=Counters{};
    RngSeedManager::SetSeed(1);RngSeedManager::SetRun(run);
    NodeContainer nodes;nodes.Create(3);
    for(unsigned i=0;i<3;++i) {
        Ptr<ConstantPositionMobilityModel> m=CreateObject<ConstantPositionMobilityModel>();
        double d=(mode=="contending")?50.:100.;
        m->SetPosition(Vector(i==1?-d:(i==2?d:0.),0,0));nodes.Get(i)->AggregateObject(m);
    }
    Ptr<SingleModelSpectrumChannel> channel=CreateObject<SingleModelSpectrumChannel>();
    Ptr<RangePropagationLossModel> loss=CreateObject<RangePropagationLossModel>();
    loss->SetAttribute("MaxRange",DoubleValue(120.));
    channel->AddPropagationLossModel(loss);
    channel->SetPropagationDelayModel(CreateObject<ConstantSpeedPropagationDelayModel>());
    LrWpanHelper helper;helper.SetChannel(channel);
    NetDeviceContainer dev=helper.Install(nodes);helper.CreateAssociatedPan(dev,0);helper.AssignStreams(dev,100);
    std::array<Ptr<LrWpanNetDevice>,3> radio;
    for(unsigned i=0;i<3;++i) {
        radio[i]=DynamicCast<LrWpanNetDevice>(dev.Get(i));
        if(!radio[i]->GetPhy()->TraceConnectWithoutContext("PhyTxBegin",MakeBoundCallback(&OnTx,i)))NS_FATAL_ERROR("PhyTxBegin not connected");
        if(!radio[i]->GetPhy()->TraceConnectWithoutContext("TrxState",MakeBoundCallback(&OnState,i)))NS_FATAL_ERROR("TrxState not connected");
        if(i>0) {
            radio[i]->GetMac()->SetMcpsDataConfirmCallback(MakeBoundCallback(&OnConfirm,i));
            radio[i]->GetMac()->SetMacMaxFrameRetries(3);
            radio[i]->GetCsmaCa()->SetMacMinBE(3);radio[i]->GetCsmaCa()->SetMacMaxBE(5);
            radio[i]->GetCsmaCa()->SetMacMaxCSMABackoffs(4);
        }
    }
    radio[0]->GetMac()->SetMcpsDataIndicationCallback(MakeCallback(&OnRx));
    radio[0]->GetPhy()->TraceConnectWithoutContext("PhyRxDrop",MakeCallback(&OnDrop));
    McpsDataRequestParams req;
    req.m_dstPanId=0;req.m_srcAddrMode=SHORT_ADDR;req.m_dstAddrMode=SHORT_ADDR;
    req.m_dstAddr=radio[0]->GetMac()->GetShortAddress();req.m_txOptions=TX_OPTION_ACK;
    z.start[1]=1.0;Simulator::Schedule(Seconds(z.start[1]),&Send,radio[1]->GetMac(),req,1u);
    unsigned senderCount=mode=="single"?1:2;
    if(senderCount==2) {
        z.start[2]=mode=="serial"?1.1:1.0;
        Simulator::Schedule(Seconds(z.start[2]),&Send,radio[2]->GetMac(),req,2u);
    }
    Simulator::Stop(Seconds(2.0));Simulator::Run();
    double end=std::max(z.lastConfirm[1],z.lastConfirm[2]);
    if(end<1.0)end=2.0;
    double energy=Energy(0,1.0,end)+Energy(1,1.0,end)+(senderCount==2?Energy(2,1.0,end):0.);
    for(unsigned i=1;i<=senderCount;++i) {
        std::cout<<mode<<","<<run<<","<<i<<","<<radio[0]->GetMtu()<<","
                 <<z.confirms[i]<<","<<z.success[i]<<","<<z.noAck[i]<<","<<z.accessFail[i]<<","<<z.other[i]<<","
                 <<z.uniqueRx[i]<<","<<(z.mask[i]==31)<<","<<(z.success[i]==5)<<","
                 <<(z.lastConfirm[i]>0?(z.lastConfirm[i]-z.start[i])*1000:-1)<<","
                 <<(z.mask[i]==31?(z.lastRx[i]-z.start[i])*1000:-1)<<","
                 <<z.phyTx[i]<<","<<z.phyTxBytes[i]<<","<<z.phyTx[0]<<","<<z.phyTxBytes[0]<<","
                 <<z.rxDrop<<","<<z.badPayload<<","<<energy<<","<<end-1.0<<"\n";
    }
    Simulator::Destroy();
}
int main(int argc,char**argv) {
    unsigned trials=128;CommandLine cmd;cmd.AddValue("trials","runs per mode",trials);cmd.Parse(argc,argv);
    if(trials<1||trials>1000)return 2;
    std::cout<<std::setprecision(12);
    std::cout<<"mode,run,sender,mtu,confirms,ack_success,no_ack,access_fail,other,"
                "distinct_fragments,message_received,all_sender_acks,confirm_ms,reassembly_ms,"
                "sender_phy_tx_frames,sender_phy_tx_bytes,sink_phy_tx_frames,sink_phy_tx_bytes,"
                "sink_phy_drops,bad_payloads,group_radio_energy_j,group_window_s\n";
    for(auto mode:{"single","serial","contending","hidden"})
        for(unsigned run=1;run<=trials;++run)Run(mode,run);
}
