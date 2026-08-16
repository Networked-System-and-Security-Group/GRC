#include "flow-id-num-tag.h"

namespace ns3 {
	NS_OBJECT_ENSURE_REGISTERED(FlowIDNUMTag);

	FlowIDNUMTag::FlowIDNUMTag() :
		Tag(),
		flow_stat(0),
		ack_req(0),
		fec_enabled(0),
		fec_pkt_role(FEC_PKT_ROLE_NONE),
		fec_group_id(0),
		fec_group_m(0),
		fec_group_n(0),
		fec_group_data_start_seq(0),
		fec_data_idx(0),
		fec_repair_idx(0),
		fec_repair_seq(0),
		fec_tx_ordinal(0)
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
		return sizeof(flow_stat) + sizeof(flow_size) + sizeof(ack_req) +
			   sizeof(fec_enabled) + sizeof(fec_pkt_role) + sizeof(fec_group_id) +
			   sizeof(fec_group_m) + sizeof(fec_group_n) + sizeof(fec_group_data_start_seq) +
			   sizeof(fec_data_idx) + sizeof(fec_repair_idx) + sizeof(fec_repair_seq) +
			   sizeof(fec_tx_ordinal);
	}

	void FlowIDNUMTag::Serialize(TagBuffer i) const
	{
		i.WriteU32(flow_stat);
		i.WriteU32(flow_size);
		i.WriteU8(ack_req);
		i.WriteU8(fec_enabled);
		i.WriteU8(fec_pkt_role);
		i.WriteU32(fec_group_id);
		i.WriteU16(fec_group_m);
		i.WriteU16(fec_group_n);
		i.WriteU32(fec_group_data_start_seq);
		i.WriteU16(fec_data_idx);
		i.WriteU16(fec_repair_idx);
		i.WriteU32(fec_repair_seq);
		i.WriteU16(fec_tx_ordinal);
	}

	void FlowIDNUMTag::Deserialize(TagBuffer i)
	{
		flow_stat = i.ReadU32();
		flow_size = i.ReadU32();
		ack_req = i.ReadU8();
		fec_enabled = i.ReadU8();
		fec_pkt_role = i.ReadU8();
		fec_group_id = i.ReadU32();
		fec_group_m = i.ReadU16();
		fec_group_n = i.ReadU16();
		fec_group_data_start_seq = i.ReadU32();
		fec_data_idx = i.ReadU16();
		fec_repair_idx = i.ReadU16();
		fec_repair_seq = i.ReadU32();
		fec_tx_ordinal = i.ReadU16();
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

	void FlowIDNUMTag::SetFecEnabled(uint8_t enabled)
	{
		fec_enabled = enabled;
	}

	uint8_t FlowIDNUMTag::GetFecEnabled() const
	{
		return fec_enabled;
	}

	void FlowIDNUMTag::SetFecPktRole(uint8_t role)
	{
		fec_pkt_role = role;
	}

	uint8_t FlowIDNUMTag::GetFecPktRole() const
	{
		return fec_pkt_role;
	}

	void FlowIDNUMTag::SetFecGroupId(uint32_t id)
	{
		fec_group_id = id;
	}

	uint32_t FlowIDNUMTag::GetFecGroupId() const
	{
		return fec_group_id;
	}

	void FlowIDNUMTag::SetFecGroupM(uint16_t m)
	{
		fec_group_m = m;
	}

	uint16_t FlowIDNUMTag::GetFecGroupM() const
	{
		return fec_group_m;
	}

	void FlowIDNUMTag::SetFecGroupN(uint16_t n)
	{
		fec_group_n = n;
	}

	uint16_t FlowIDNUMTag::GetFecGroupN() const
	{
		return fec_group_n;
	}

	void FlowIDNUMTag::SetFecGroupDataStartSeq(uint32_t seq)
	{
		fec_group_data_start_seq = seq;
	}

	uint32_t FlowIDNUMTag::GetFecGroupDataStartSeq() const
	{
		return fec_group_data_start_seq;
	}

	void FlowIDNUMTag::SetFecDataIdx(uint16_t idx)
	{
		fec_data_idx = idx;
	}

	uint16_t FlowIDNUMTag::GetFecDataIdx() const
	{
		return fec_data_idx;
	}

	void FlowIDNUMTag::SetFecRepairIdx(uint16_t idx)
	{
		fec_repair_idx = idx;
	}

	uint16_t FlowIDNUMTag::GetFecRepairIdx() const
	{
		return fec_repair_idx;
	}

	void FlowIDNUMTag::SetFecRepairSeq(uint32_t seq)
	{
		fec_repair_seq = seq;
	}

	uint32_t FlowIDNUMTag::GetFecRepairSeq() const
	{
		return fec_repair_seq;
	}

	void FlowIDNUMTag::SetFecTxOrdinal(uint16_t idx)
	{
		fec_tx_ordinal = idx;
	}

	uint16_t FlowIDNUMTag::GetFecTxOrdinal() const
	{
		return fec_tx_ordinal;
	}

	void FlowIDNUMTag::Print(std::ostream &os) const
	{
		os << "Flow Stat: " << flow_stat
		   << ", Flow Size: " << flow_size
		   << ", Ack Req: " << (int)ack_req
		   << ", FEC Enabled: " << (int)fec_enabled
		   << ", FEC Role: " << (int)fec_pkt_role
		   << ", FEC Group: " << fec_group_id
		   << ", FEC m/n: " << fec_group_m << "/" << fec_group_n
		   << ", FEC Data Start Seq: " << fec_group_data_start_seq
		   << ", FEC Data Idx: " << fec_data_idx
		   << ", FEC Repair Idx: " << fec_repair_idx
		   << ", FEC Repair Seq: " << fec_repair_seq
		   << ", FEC Tx Ordinal: " << fec_tx_ordinal;
	}

} // namespace ns3
