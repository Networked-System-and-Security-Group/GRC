#ifndef FLOW_ID_NUM_TAG_H
#define FLOW_ID_NUM_TAG_H

#include "ns3/tag.h"

namespace ns3 {
	/**
	* \ingroup tlt
	* \brief The packet header for a TLT packet
	*/
	class FlowIDNUMTag : public Tag
	{
	public:
		enum FecPktRole : uint8_t {
			FEC_PKT_ROLE_NONE = 0,
			FEC_PKT_ROLE_REPAIR = 1,
			FEC_PKT_ROLE_DATA = 2,
		};

		FlowIDNUMTag();
		static TypeId GetTypeId(void);
		virtual TypeId GetInstanceTypeId(void) const;
		virtual void Print(std::ostream &os) const;
		virtual uint32_t GetSerializedSize(void) const;
		virtual void Serialize(TagBuffer i) const;
		virtual void Deserialize(TagBuffer i);
		void SetId(int32_t ttl);
		int32_t GetId();
		uint32_t Getflowid();
		uint32_t GetFlowSize();
		void SetFlowSize(uint32_t fs);
		void SetAckReq(uint8_t ack);  // Setter for ack_req
		uint8_t GetAckReq() const;    // Getter for ack_req
		void SetFecEnabled(uint8_t enabled);
		uint8_t GetFecEnabled() const;
		void SetFecPktRole(uint8_t role);
		uint8_t GetFecPktRole() const;
		void SetFecGroupId(uint32_t id);
		uint32_t GetFecGroupId() const;
		void SetFecGroupM(uint16_t m);
		uint16_t GetFecGroupM() const;
		void SetFecGroupN(uint16_t n);
		uint16_t GetFecGroupN() const;
		void SetFecGroupDataStartSeq(uint32_t seq);
		uint32_t GetFecGroupDataStartSeq() const;
		void SetFecDataIdx(uint16_t idx);
		uint16_t GetFecDataIdx() const;
		void SetFecRepairIdx(uint16_t idx);
		uint16_t GetFecRepairIdx() const;
		void SetFecRepairSeq(uint32_t seq);
		uint32_t GetFecRepairSeq() const;
		void SetFecTxOrdinal(uint16_t idx);
		uint16_t GetFecTxOrdinal() const;
		
	private:
		int32_t flow_stat;
		uint32_t flow_size;
		uint8_t ack_req;             // New member for acknowledgment request
		uint8_t fec_enabled;
		uint8_t fec_pkt_role;
		uint32_t fec_group_id;
		uint16_t fec_group_m;
		uint16_t fec_group_n;
		uint32_t fec_group_data_start_seq;
		uint16_t fec_data_idx;
		uint16_t fec_repair_idx;
		uint32_t fec_repair_seq;
		uint16_t fec_tx_ordinal;
		static uint16_t global_FLOWID_counter;
	};
} // namespace ns3

#endif /* FLOW_ID_NUM_TAG_H */
