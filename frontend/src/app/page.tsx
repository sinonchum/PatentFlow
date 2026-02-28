"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UploadCloud, FileText, Zap, Download, ChevronRight, Sparkles, Shield, BarChart3, Languages, FileEdit } from "lucide-react";

export default function Workspace() {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white font-sans relative overflow-x-hidden">
      {/* Background gradient effects */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[600px] h-[600px] bg-purple-600/10 rounded-full blur-[120px]" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[500px] h-[500px] bg-blue-600/8 rounded-full blur-[100px]" />
        <div className="absolute top-[40%] right-[20%] w-[300px] h-[300px] bg-indigo-500/5 rounded-full blur-[80px]" />
      </div>

      {/* Top Nav */}
      <nav className="relative z-10 border-b border-white/[0.06] bg-black/20 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center">
              <Zap className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-semibold tracking-tight">PatentFlow</span>
            <span className="text-xs text-white/30 font-medium ml-1 hidden sm:inline">v2.0</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-white/40 font-medium hidden md:inline">Document Processing Workspace</span>
            <div className="h-4 w-px bg-white/10 hidden md:block" />
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-emerald-400 font-medium">Local Mode</span>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero / Upload Section */}
      <section className="relative z-10 max-w-7xl mx-auto px-6 pt-12 pb-8">
        <div className="mb-10">
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight mb-3">
            <span className="bg-gradient-to-r from-white via-white to-white/60 bg-clip-text text-transparent">
              Document Processing
            </span>
          </h1>
          <p className="text-white/40 text-sm max-w-xl leading-relaxed">
            Upload your EPO Office Action and Patent Specification to generate Art. 56 claim charts,
            translation verification tables, and response drafts.
          </p>
        </div>

        {/* Upload Cards + Config Row */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Office Action Upload */}
          <div className="group relative rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5 hover:border-purple-500/30 hover:bg-white/[0.05] transition-all duration-300 cursor-pointer">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center flex-shrink-0 group-hover:bg-purple-500/20 transition-colors">
                <UploadCloud className="w-5 h-5 text-purple-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white/90 mb-1">Office Action</p>
                <p className="text-xs text-white/30">PDF or TXT format</p>
              </div>
            </div>
            <div className="mt-4 border border-dashed border-white/10 rounded-lg p-3 text-center hover:border-purple-500/30 transition-colors">
              <p className="text-xs text-white/25">Drop file or click to browse</p>
            </div>
          </div>

          {/* Patent Specification Upload */}
          <div className="group relative rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5 hover:border-blue-500/30 hover:bg-white/[0.05] transition-all duration-300 cursor-pointer">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-500/20 transition-colors">
                <FileText className="w-5 h-5 text-blue-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white/90 mb-1">Patent Specification</p>
                <p className="text-xs text-white/30">PDF, TXT, or DOCX</p>
              </div>
            </div>
            <div className="mt-4 border border-dashed border-white/10 rounded-lg p-3 text-center hover:border-blue-500/30 transition-colors">
              <p className="text-xs text-white/25">Drop file or click to browse</p>
            </div>
          </div>

          {/* Configuration */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5">
            <div className="space-y-4">
              <div>
                <Label className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 block">
                  Examiner Bias
                </Label>
                <Select defaultValue="telecom">
                  <SelectTrigger className="w-full bg-white/[0.04] border-white/[0.08] text-white/80 text-sm h-9 rounded-lg hover:border-white/20 transition-colors">
                    <SelectValue placeholder="Select examiner" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1a1a2e] border-white/10">
                    <SelectItem value="telecom">Jukka Tapaninen — Telecom</SelectItem>
                    <SelectItem value="mechanics">Maria Schmidt — Mechanics</SelectItem>
                    <SelectItem value="chemistry">Hans Mueller — Chemistry</SelectItem>
                    <SelectItem value="unbiased">General — No Bias</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 block">
                  Claim Type
                </Label>
                <Select defaultValue="method">
                  <SelectTrigger className="w-full bg-white/[0.04] border-white/[0.08] text-white/80 text-sm h-9 rounded-lg hover:border-white/20 transition-colors">
                    <SelectValue placeholder="Select claim type" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1a1a2e] border-white/10">
                    <SelectItem value="method">Method</SelectItem>
                    <SelectItem value="apparatus">Apparatus</SelectItem>
                    <SelectItem value="system">System</SelectItem>
                    <SelectItem value="product">Product</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {/* Execute Button */}
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm p-5 flex flex-col justify-between">
            <div className="mb-4">
              <p className="text-sm font-medium text-white/70 mb-1">Ready to process</p>
              <p className="text-xs text-white/30 leading-relaxed">
                Pipeline generates claim charts, translation tables, and response drafts.
              </p>
            </div>
            <Button className="w-full bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white border-0 rounded-lg h-10 font-medium text-sm shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 transition-all duration-300 group">
              <Sparkles className="w-4 h-4 mr-2 group-hover:animate-spin" />
              Execute Pipeline
              <ChevronRight className="w-4 h-4 ml-1 opacity-60 group-hover:translate-x-0.5 transition-transform" />
            </Button>
          </div>
        </div>
      </section>

      {/* Tabs Section */}
      <section className="relative z-10 max-w-7xl mx-auto px-6 pb-16">
        <Tabs defaultValue="claim-chart" className="w-full">
          <TabsList className="bg-transparent border-b border-white/[0.06] rounded-none p-0 h-auto justify-start space-x-1 mb-0">
            <TabsTrigger
              value="claim-chart"
              className="rounded-none rounded-t-lg border-b-2 border-transparent data-[state=active]:border-purple-500 data-[state=active]:text-white data-[state=active]:bg-white/[0.04] bg-transparent px-4 py-3 text-sm font-medium text-white/40 hover:text-white/70 transition-all gap-2"
            >
              <BarChart3 className="w-4 h-4" />
              Art. 56 Claim Chart
            </TabsTrigger>
            <TabsTrigger
              value="verifier"
              className="rounded-none rounded-t-lg border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:text-white data-[state=active]:bg-white/[0.04] bg-transparent px-4 py-3 text-sm font-medium text-white/40 hover:text-white/70 transition-all gap-2"
            >
              <Languages className="w-4 h-4" />
              Art. 123(2) Verifier
            </TabsTrigger>
            <TabsTrigger
              value="draft"
              className="rounded-none rounded-t-lg border-b-2 border-transparent data-[state=active]:border-indigo-500 data-[state=active]:text-white data-[state=active]:bg-white/[0.04] bg-transparent px-4 py-3 text-sm font-medium text-white/40 hover:text-white/70 transition-all gap-2"
            >
              <FileEdit className="w-4 h-4" />
              Response Draft
            </TabsTrigger>
          </TabsList>

          {/* Tab 1: Claim Chart */}
          <TabsContent value="claim-chart" className="mt-0">
            <div className="rounded-b-xl rounded-tr-xl border border-white/[0.06] border-t-0 bg-white/[0.02] backdrop-blur-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead>
                    <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                      <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-16">ID</th>
                      <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest">Claim Limitation</th>
                      <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest">Prior Art (D1)</th>
                      <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-36">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top font-mono text-sm text-purple-400/80">1.1</td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">
                        A method for wireless communication, comprising: transmitting a downlink control information (DCI) format;
                      </td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">
                        D1 discloses a base station transmitting resource allocation via a control channel (paragraph [0045]).
                      </td>
                      <td className="px-6 py-5 align-top">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white/[0.06] text-white/50 border border-white/[0.08]">
                          Disclosed
                        </span>
                      </td>
                    </tr>
                    <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top font-mono text-sm text-purple-400/80">1.2</td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">
                        determining a timing offset K0 dynamically based on the received DCI format parameters;
                      </td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">
                        D1 utilizes a fixed timing offset via RRC signaling (paragraph [0052]). No dynamic DCI determination.
                      </td>
                      <td className="px-6 py-5 align-top">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                          Distinguishing
                        </span>
                      </td>
                    </tr>
                    <tr className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top font-mono text-sm text-purple-400/80">1.3</td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">
                        receiving a PDSCH based on the dynamically determined timing offset K0.
                      </td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">
                        D1 describes PDSCH reception based on a fixed scheduling timeline (FIG. 4).
                      </td>
                      <td className="px-6 py-5 align-top">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white/[0.06] text-white/50 border border-white/[0.08]">
                          Disclosed
                        </span>
                      </td>
                    </tr>
                    <tr className="border-t border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top font-mono text-sm text-purple-400/80">1.4</td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">
                        wherein the terminal device is configured to determine the timing offset based on DCI format characteristics.
                      </td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">
                        D1 does not disclose configuration for DCI-based timing offset determination at the terminal side.
                      </td>
                      <td className="px-6 py-5 align-top">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                          Distinguishing
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              {/* Summary bar */}
              <div className="border-t border-white/[0.06] bg-white/[0.02] px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Shield className="w-4 h-4 text-emerald-400/80" />
                  <span className="text-xs text-white/50">
                    <span className="text-emerald-400 font-medium">2 distinguishing features</span> identified over D1 supporting inventive step under Art. 56 EPC
                  </span>
                </div>
                <Button variant="ghost" className="text-xs text-white/30 hover:text-white/60 h-8 px-3 gap-1.5">
                  <Download className="w-3.5 h-3.5" />
                  Export
                </Button>
              </div>
            </div>
          </TabsContent>

          {/* Tab 2: Translation Verifier */}
          <TabsContent value="verifier" className="mt-0">
            <div className="rounded-b-xl rounded-tr-xl border border-white/[0.06] border-t-0 bg-white/[0.02] backdrop-blur-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead>
                    <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                      <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-1/3">Original (CN)</th>
                      <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-1/3">Translation (EN)</th>
                      <th className="px-6 py-4 text-xs font-semibold text-white/30 uppercase tracking-widest w-1/3">Back-Translation (CN)</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top text-white/60 leading-relaxed">一种无线通信方法，包括：</td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">A method for wireless communication, comprising:</td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">一种用于无线通信的方法，包括：</td>
                    </tr>
                    <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top text-white/60 leading-relaxed">
                        <span className="text-amber-400/90 underline decoration-amber-500/30 underline-offset-2">发送</span>下行控制信息DCI格式；
                      </td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">
                        <span className="bg-amber-500/15 text-amber-300 px-1.5 py-0.5 rounded border border-amber-500/20 text-xs font-medium">transmitting</span>{" "}
                        a downlink control information (DCI) format;
                      </td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">
                        <span className="bg-amber-500/10 text-amber-400/80 px-1.5 py-0.5 rounded border border-amber-500/15 text-xs">传输</span>下行控制信息(DCI)格式；
                      </td>
                    </tr>
                    <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top text-white/60 leading-relaxed">确定定时偏移量K0；</td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">determining a timing offset K0;</td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">确定定时偏移量K0；</td>
                    </tr>
                    <tr className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-5 align-top text-white/60 leading-relaxed">
                        基于该定时偏移量<span className="text-amber-400/90 underline decoration-amber-500/30 underline-offset-2">接收</span>物理下行共享信道PDSCH。
                      </td>
                      <td className="px-6 py-5 align-top text-white/80 leading-relaxed">
                        <span className="bg-amber-500/15 text-amber-300 px-1.5 py-0.5 rounded border border-amber-500/20 text-xs font-medium">receiving</span>{" "}
                        a PDSCH based on the timing offset.
                      </td>
                      <td className="px-6 py-5 align-top text-white/50 leading-relaxed">
                        基于该定时偏移量<span className="bg-amber-500/10 text-amber-400/80 px-1.5 py-0.5 rounded border border-amber-500/15 text-xs">接收</span>物理下行共享信道PDSCH。
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="border-t border-white/[0.06] bg-white/[0.02] px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-sm bg-amber-500/20 border border-amber-500/30" />
                    <span className="text-xs text-white/40">Verb mismatch flagged</span>
                  </div>
                  <span className="text-xs text-white/30">|</span>
                  <span className="text-xs text-amber-400/70 font-medium">2 discrepancies detected</span>
                </div>
                <Button variant="ghost" className="text-xs text-white/30 hover:text-white/60 h-8 px-3 gap-1.5">
                  <Download className="w-3.5 h-3.5" />
                  Export
                </Button>
              </div>
            </div>
          </TabsContent>

          {/* Tab 3: Response Draft */}
          <TabsContent value="draft" className="mt-0">
            <div className="rounded-b-xl rounded-tr-xl border border-white/[0.06] border-t-0 bg-white/[0.02] backdrop-blur-sm overflow-hidden">
              <div className="max-w-3xl mx-auto p-8 md:p-12 space-y-6 text-white/80 leading-relaxed text-sm">
                <div className="mb-10 border-b border-white/[0.06] pb-6">
                  <div className="flex justify-between items-start flex-wrap gap-4">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-purple-400/60 mb-2">
                        Response to European Patent Office
                      </p>
                      <h2 className="text-xl font-semibold text-white tracking-tight">
                        Art. 56 Inventive Step Objection
                      </h2>
                    </div>
                    <div className="text-right text-xs text-white/30 space-y-1">
                      <p>Date: 28 February 2026</p>
                      <p>Application No. EP 21 823 456.7</p>
                    </div>
                  </div>
                </div>

                <p>Dear Examiner Tapaninen,</p>

                <p className="text-white/70">
                  The Applicant respectfully responds to the Office Action and submits the following observations
                  regarding the inventive step objection under Art. 56 EPC against the independent method claim.
                </p>

                <h3 className="font-semibold text-base mt-10 mb-3 text-white/90 flex items-center gap-2">
                  <span className="w-1 h-6 rounded-full bg-gradient-to-b from-purple-500 to-blue-500 inline-block" />
                  1. Distinguishing Features Over D1
                </h3>
                <p className="text-white/70">
                  The independent claim contains technical features not disclosed in D1. Specifically,
                  the claimed method comprises determining a timing offset K0{" "}
                  <span className="text-white font-medium bg-white/[0.06] px-1.5 py-0.5 rounded">
                    dynamically based on the received DCI format parameters
                  </span>.
                </p>
                <p className="text-white/70">
                  In contrast, D1 (US 2021/0123456 A1) utilizes a fixed timing offset configured exclusively
                  via higher-layer RRC signaling, as detailed in paragraph [0052].
                </p>

                <h3 className="font-semibold text-base mt-10 mb-3 text-white/90 flex items-center gap-2">
                  <span className="w-1 h-6 rounded-full bg-gradient-to-b from-blue-500 to-indigo-500 inline-block" />
                  2. Technical Effects and Advantages
                </h3>
                <p className="text-white/70">
                  The objective technical problem may be formulated as how to increase scheduling flexibility
                  and reduce latency in HARQ-ACK feedback processing within dynamic 5G NR deployments.
                  The claimed dynamic determination provides adaptive scheduling inherently absent in D1.
                </p>

                <div className="mt-12 pt-6 border-t border-white/[0.06]">
                  <p className="text-white/40 italic">
                    The Applicant respectfully requests that the objection be withdrawn and the application proceed to grant.
                  </p>
                </div>
              </div>
              <div className="border-t border-white/[0.06] bg-white/[0.02] px-6 py-4 flex items-center justify-end gap-3">
                <Button variant="ghost" className="text-xs text-white/30 hover:text-white/60 h-8 px-3 gap-1.5">
                  <Download className="w-3.5 h-3.5" />
                  Export TXT
                </Button>
                <Button variant="ghost" className="text-xs text-white/30 hover:text-white/60 h-8 px-3 gap-1.5">
                  <Download className="w-3.5 h-3.5" />
                  Export DOCX
                </Button>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/[0.04] py-8">
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-white/20">
            <Zap className="w-3.5 h-3.5" />
            <span>PatentFlow — Offline-first · Secure · EPC Compliant</span>
          </div>
          <span className="text-xs text-white/15">© 2026</span>
        </div>
      </footer>
    </div>
  );
}
