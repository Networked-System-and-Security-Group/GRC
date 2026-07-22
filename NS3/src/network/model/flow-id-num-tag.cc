#include "flow-id-num-tag.h"

namespace ns3 {
	NS_OBJECT_ENSURE_REGISTERED(FlowIDNUMTag);

	FlowIDNUMTag::FlowIDNUMTag() :
		Tag(),
		flow_stat(0),
		ack_req(0)  // Initialize ack_req to 0
	{
	}

	TypeId FlowIDNUMTag::GetTypeId(void)
	{
		static TypeId tid = TypeId("ns3::FlowIDNUMTag")
			.SetParent<Tag>()
			.AddConstructor<FlowIDNUMTag>()
			;
		return tid;
	}

	TypeId FlowIDNUMTag::GetInstanceTypeId(void) const
	{
		return GetTypeId();
	}

	uint32_t FlowIDNUMTag::GetSerializedSize(void) const
	{
		return sizeof(flow_stat) + sizeof(flow_size) + sizeof(ack_req);
	}

	void FlowIDNUMTag::Serialize(TagBuffer i) const
	{
		i.WriteU32(flow_stat);
		i.WriteU32(flow_size);
		i.WriteU8(ack_req);
	}

	void FlowIDNUMTag::Deserialize(TagBuffer i)
	{
		flow_stat = i.ReadU32();
		flow_size = i.ReadU32();
		ack_req = i.ReadU8();
	}

	void FlowIDNUMTag::SetId(int32_t ttl)
	{
		flow_stat = ttl;
	}

	int32_t FlowIDNUMTag::GetId()
	{
		return flow_stat;
	}

	uint32_t FlowIDNUMTag::Getflowid()
	{
		static uint32_t nextFlowId = 0;
		flow_stat = nextFlowId++;
		return flow_stat;
	}

	uint32_t FlowIDNUMTag::GetFlowSize()
	{
		return flow_size;
	}

	void FlowIDNUMTag::SetFlowSize(uint32_t fs)
	{
		flow_size = fs;
	}

	void FlowIDNUMTag::SetAckReq(uint8_t ack)
	{
		ack_req = ack;  // Set ack_req value
	}

	uint8_t FlowIDNUMTag::GetAckReq() const
	{
		return ack_req;  // Get ack_req value
	}

	void FlowIDNUMTag::Print(std::ostream &os) const
	{
		os << "Flow Stat: " << flow_stat << ", Flow Size: " << flow_size << ", Ack Req: " << (int)ack_req;
	}

} // namespace ns3
