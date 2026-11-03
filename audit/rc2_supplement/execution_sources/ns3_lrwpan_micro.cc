// Standalone LR-WPAN component check; does not execute JLC-R or compare policies.
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/mobility-module.h"
#include "ns3/propagation-module.h"
#include "ns3/spectrum-module.h"
#include "ns3/lr-wpan-module.h"
#include <iostream>
#include <string>

using namespace ns3;
static uint32_t received = 0;
static uint32_t phyDrops = 0;
static uint32_t success = 0;
static uint32_t noAck = 0;
static uint32_t tooLong = 0;
static uint32_t other = 0;

static void OnRx(McpsDataIndicationParams, Ptr<Packet>) { ++received; }
static void OnDrop(Ptr<const Packet>) { ++phyDrops; }
static void OnConfirm(McpsDataConfirmParams p) {
    if (p.m_status == LrWpanMacStatus::SUCCESS) ++success;
    else if (p.m_status == LrWpanMacStatus::NO_ACK) ++noAck;
    else if (p.m_status == LrWpanMacStatus::FRAME_TOO_LONG) ++tooLong;
    else ++other;
}

int main(int argc, char **argv) {
    std::string mode="single";
    CommandLine cmd;
    cmd.AddValue("mode", "single, serial, hidden or oversize", mode);
    cmd.Parse(argc,argv);
    if (mode!="single" && mode!="serial" && mode!="hidden" && mode!="oversize") return 2;
    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(1);
    NodeContainer nodes;
    nodes.Create(3);
    for (uint32_t i=0;i<3;++i) {
        Ptr<ConstantPositionMobilityModel> p=CreateObject<ConstantPositionMobilityModel>();
        p->SetPosition(Vector(i==1 ? -100.0 : (i==2 ? 100.0 : 0.0),0,0));
        nodes.Get(i)->AggregateObject(p);
    }
    Ptr<SingleModelSpectrumChannel> channel=CreateObject<SingleModelSpectrumChannel>();
    Ptr<RangePropagationLossModel> loss=CreateObject<RangePropagationLossModel>();
    loss->SetAttribute("MaxRange",DoubleValue(120.0));
    channel->AddPropagationLossModel(loss);
    channel->SetPropagationDelayModel(CreateObject<ConstantSpeedPropagationDelayModel>());
    LrWpanHelper helper;
    helper.SetChannel(channel);
    NetDeviceContainer devices=helper.Install(nodes);
    helper.CreateAssociatedPan(devices,0);
    helper.AssignStreams(devices,100);
    auto receiver=DynamicCast<LrWpanNetDevice>(devices.Get(0));
    auto left=DynamicCast<LrWpanNetDevice>(devices.Get(1));
    auto right=DynamicCast<LrWpanNetDevice>(devices.Get(2));
    receiver->GetMac()->SetMcpsDataIndicationCallback(MakeCallback(&OnRx));
    receiver->GetPhy()->TraceConnectWithoutContext("PhyRxDrop",MakeCallback(&OnDrop));
    for (auto d : {left,right}) {
        d->GetMac()->SetMcpsDataConfirmCallback(MakeCallback(&OnConfirm));
        d->GetMac()->SetMacMaxFrameRetries(0);
        d->GetCsmaCa()->SetMacMinBE(0);
        d->GetCsmaCa()->SetMacMaxBE(0);
    }
    McpsDataRequestParams request;
    request.m_dstPanId=0;
    request.m_srcAddrMode=SHORT_ADDR;
    request.m_dstAddrMode=SHORT_ADDR;
    request.m_dstAddr=receiver->GetMac()->GetShortAddress();
    request.m_txOptions=TX_OPTION_ACK;
    const uint32_t bytes=(mode=="oversize") ? 500 : 100;
    Simulator::Schedule(Seconds(1.0),&LrWpanMac::McpsDataRequest,left->GetMac(),request,Create<Packet>(bytes));
    if (mode=="serial" || mode=="hidden") {
        double t=(mode=="serial") ? 1.1 : 1.0;
        request.m_msduHandle=1;
        Simulator::Schedule(Seconds(t),&LrWpanMac::McpsDataRequest,right->GetMac(),request,Create<Packet>(bytes));
    }
    Simulator::Stop(Seconds(2));
    Simulator::Run();
    std::cout << "mode="<<mode<<" mtu="<<receiver->GetMtu()<<" bytes="<<bytes
              <<" rx="<<received<<" phy_rx_drop="<<phyDrops<<" success="<<success
              <<" no_ack="<<noAck<<" frame_too_long="<<tooLong<<" other="<<other<<"\n";
    Simulator::Destroy();
}
